import os
import logging
import asyncio
import requests
import tempfile
import zipfile
import shutil
from typing import Optional, Dict, Any
from telegram import Update, InputFile
from telegram.ext import (
    Application, 
    MessageHandler, 
    CommandHandler, 
    ContextTypes, 
    filters,
    CallbackContext
)
from telegram.error import NetworkError, TimedOut
from lxml import etree

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)

# Configuration
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    raise ValueError("No TELEGRAM_BOT_TOKEN found in environment variables")

ALLOWED_FILE_SIZE = 32 * 1024 * 1024  # 32 MB in bytes
REQUEST_TIMEOUT = 60  # Timeout for requests in seconds
MAX_RETRY_ATTEMPTS = 3  # Maximum number of retry attempts for failed operations
MAX_ZIP_RATIO = 100  # Maximum allowed ratio between unpacked size and compressed size

class SecurityError(Exception):
    """Custom exception for security-related issues"""
    pass

async def get_file_path(file_id: str) -> Optional[str]:
    """Get the file path for a given file ID with retry logic"""
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            session = requests.Session()
            response = await asyncio.to_thread(
                session.get,
                f"https://api.telegram.org/bot{TOKEN}/getFile",
                params={"file_id": file_id},
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()
            
            if not result.get("ok"):
                logger.error(f"API returned error: {result}")
                return None
                
            return f"https://api.telegram.org/file/bot{TOKEN}/{result['result']['file_path']}"
        except (requests.RequestException, asyncio.TimeoutError) as e:
            logger.warning(f"Attempt {attempt+1}/{MAX_RETRY_ATTEMPTS} failed: {e}")
            if attempt == MAX_RETRY_ATTEMPTS - 1:
                logger.error(f"Failed to get file path after {MAX_RETRY_ATTEMPTS} attempts")
                return None
            await asyncio.sleep(2 ** attempt)  # Exponential backoff

async def send_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Send a text reply with error handling"""
    try:
        await update.message.reply_text(text)
    except (NetworkError, TimedOut) as e:
        logger.error(f"Network error when sending reply: {e}")
        # Schedule a retry with exponential backoff
        retry_after = min(30, context.user_data.get("retry_count", 0) * 5 + 1)
        context.user_data["retry_count"] = context.user_data.get("retry_count", 0) + 1
        
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(retry_send_message(update.effective_chat.id, text, ctx)),
            retry_after
        )

async def retry_send_message(chat_id: int, text: str, context: CallbackContext) -> None:
    """Retry sending a message"""
    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
        # Reset retry counter on success
        if "retry_count" in context.user_data:
            del context.user_data["retry_count"]
    except Exception as e:
        logger.error(f"Failed to retry sending message: {e}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document uploads"""
    document = update.message.document
    file_id = document.file_id
    file_size = document.file_size
    file_name = document.file_name or "unknown"
    
    # Log the file processing
    user_info = f"@{update.effective_user.username}" if update.effective_user.username else f"ID:{update.effective_user.id}"
    logger.info(f"Processing document {file_name} ({file_size} bytes) from user {user_info}")

    # File size validation
    if file_size > ALLOWED_FILE_SIZE:
        await send_reply(update, context, 'The file exceeds the maximum allowed size of 32 MB.')
        return

    # Проверка расширения файла
    if not file_name.lower().endswith('.zip'):
        await send_reply(update, context, 'Please send a file with .zip extension')
        return

    # Show processing status
    status_message = await update.message.reply_text("Processing your file... ⏳")
    
    try:
        # Get file path
        file_url = await get_file_path(file_id)
        if not file_url:
            await status_message.edit_text('Failed to retrieve file. Please try again.')
            return

        # Download the file
        tmp_path = None
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(prefix="tg_unzip_")
            os.close(tmp_fd)
            
            session = requests.Session()
            response = await asyncio.to_thread(
                session.get,
                file_url,
                stream=True,
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            with open(tmp_path, 'wb') as tmp:
                for chunk in response.iter_content(chunk_size=8192):
                    tmp.write(chunk)
            
            await status_message.edit_text("File downloaded, extracting contents... ⏳")
        except (requests.RequestException, asyncio.TimeoutError) as e:
            logger.error(f"File download error: {e}")
            await status_message.edit_text('Failed to download file. Please try later.')
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
            return

        # Process the archive
        extract_dir = None
        try:
            extract_dir = tempfile.mkdtemp(prefix="tg_extract_")
            await process_archive(update, context, tmp_path, extract_dir, status_message)
        except SecurityError as e:
            await status_message.edit_text(str(e))
        except Exception as e:
            logger.error(f"Archive processing error: {e}", exc_info=True)
            await status_message.edit_text('An error occurred while processing the archive. Please try again.')
        finally:
            # Clean up temp files
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
            if extract_dir and os.path.exists(extract_dir):
                shutil.rmtree(extract_dir, ignore_errors=True)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        await status_message.edit_text('An unexpected error occurred. Please try again.')

async def process_archive(update: Update, context: ContextTypes.DEFAULT_TYPE, archive_path: str, 
                         extract_path: str, status_message) -> None:
    """Process the archive file"""
    # Validate archive
    try:
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            # Check number of files - only one file should be present
            info_list = zip_ref.infolist()
            
            actual_files = [item for item in info_list]
            
            if len(actual_files) != 1:
                raise SecurityError('The archive must contain exactly one .fb2 file. Processing stopped.')
            
            # Check file extension
            if not actual_files[0].filename.lower().endswith('.fb2'):
                raise SecurityError('The file in the archive must have .fb2 extension. Other formats are not supported.')
            
            # File name security check
            inner_path = actual_files[0].filename

            if '/' in inner_path or '\\' in inner_path:
                raise SecurityError('The archive must contain a single file at the root level (no folders).')

            # Disallow absolute paths, up-level navigation, and nested directories
            if (
                inner_path.startswith('/') or
                '..' in inner_path or
                os.path.normpath(inner_path) != os.path.basename(inner_path)
            ):
                raise SecurityError('The archive must contain a single file at the root (no folders).')
                        
            # Check for zip bomb
            file_item = actual_files[0]
            if file_item.compress_size > 0 and file_item.file_size / file_item.compress_size > MAX_ZIP_RATIO:
                raise SecurityError('Suspicious compression ratio. Processing stopped for security reasons.')
            
            # Check total unpacked size
            if file_item.file_size > ALLOWED_FILE_SIZE:
                raise SecurityError('Unpacked file size exceeds the allowed limit.')
            
            # Extract file
            safe_extract(zip_ref, extract_path)
            
    except zipfile.BadZipFile:
        await status_message.edit_text('The file is not a valid zip archive.')
        return
    
    # Process FB2 file
    await status_message.edit_text("Checking for FB2 file... ⏳")
    
    # Get path to FB2 file (we know there's only one)
    fb2_path = os.path.join(extract_path, actual_files[0].filename)
    
    try:
        # Extract book metadata
        metadata = await extract_fb2_metadata(fb2_path)
        
        # Send the file
        with open(fb2_path, 'rb') as fb2_file:
            # Generate caption based on metadata
            caption = generate_fb2_caption(metadata)
            
            await update.message.reply_document(
                document=InputFile(fb2_file, filename=os.path.basename(fb2_path)),
                caption=caption
            )
        
        await status_message.edit_text("File successfully processed! ✅")
    except Exception as e:
        logger.error(f"Error processing FB2 file {fb2_path}: {e}", exc_info=True)
        await status_message.edit_text("Failed to process FB2 file. The file may be corrupted.")

def safe_extract(zip_file, path):
    for member in zip_file.infolist():
        member_path = os.path.realpath(os.path.join(path, member.filename))
        if not member_path.startswith(os.path.realpath(path)):
            raise SecurityError("Potential Zip Slip attack detected.")
    zip_file.extractall(path)

async def extract_fb2_metadata(fb2_path: str) -> Dict[str, Any]:
    """Extract metadata from FB2 file"""
    metadata = {"title": None, "author": None}
    
    try:
        # Parse with lxml but handle potential XML issues
        parser = etree.XMLParser(
            recover=True,
            resolve_entities=False,
            no_network=True,
            huge_tree=False
        )
        
        # Limit parsing for large files
        if os.path.getsize(fb2_path) > ALLOWED_FILE_SIZE:
            logger.warning(f"FB2 file too large for metadata extraction: {fb2_path}")
            return metadata
        
        tree = await asyncio.to_thread(etree.parse, fb2_path, parser)
        
        ns = {'fb': 'http://www.gribuser.ru/xml/fictionbook/2.0'}
        
        # Extract title
        title_elem = tree.find('.//fb:book-title', namespaces=ns)
        if title_elem is not None and title_elem.text:
            metadata["title"] = title_elem.text[:255]
        
        # Extract author
        author_elem = tree.find('.//fb:author', namespaces=ns)
        if author_elem is not None:
            first_name = author_elem.findtext('.//fb:first-name', namespaces=ns)
            last_name = author_elem.findtext('.//fb:last-name', namespaces=ns)
            if first_name and last_name:
                metadata["author"] = f"{first_name} {last_name}"
            elif last_name:
                metadata["author"] = last_name
            elif first_name:
                metadata["author"] = first_name
    except Exception as e:
        logger.warning(f"Failed to extract FB2 metadata: {e}")
    
    return metadata

def generate_fb2_caption(metadata: Dict[str, Any]) -> str:
    """Generate caption for FB2 file based on metadata"""
    if metadata["title"] and metadata["author"]:
        return f'📚 "{metadata["title"]}" by {metadata["author"]} has been successfully extracted!'
    elif metadata["title"]:
        return f'📚 "{metadata["title"]}" has been successfully extracted!'
    elif metadata["author"]:
        return f'📚 A book by {metadata["author"]} has been successfully extracted!'
    else:
        return '📚 Your .fb2 file has been successfully extracted from the archive! Happy reading!'

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command"""
    welcome_message = (
        'Welcome to the FB2 Unzip Bot! 🤖\n'
        'I can help you extract .fb2 files from zip archives. Just send me '
        'a zip file containing *one* FB2 file, and I will extract it for you.\n'
        'I can process archives up to 32MB in size.'
    )
    await send_reply(update, context, welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command"""
    help_text = (
        '📖 *How to use the FB2 Unzip Bot:*\n'
        '1. Send a zip file containing *only one* .fb2 file\n'
        '2. Wait while I process your file\n'
        '3. Receive the extracted .fb2 file\n'
        '*Limitations:*\n'
        '• Maximum file size: 32MB\n'
        '• Archive must contain only one file\n'
        '• Only .fb2 files are supported'
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages"""
    await send_reply(update, context, 'Please send me a zip archive containing an .fb2 file for extraction.')

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors"""
    logger.error(f"Update {update} caused error: {context.error}")
    
    # Only send message to user if we have a valid update object
    if isinstance(update, Update) and update.effective_message:
        error_message = 'Sorry, an error occurred while processing your request.'
        if isinstance(context.error, (NetworkError, TimedOut)):
            error_message = 'A network error occurred. Please try again later.'
        
        try:
            await update.effective_message.reply_text(error_message)
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")

def main() -> None:
    """Start the bot"""
    try:
        # Create the Application
        application = Application.builder().token(TOKEN).build()

        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        
        # Add error handler
        application.add_error_handler(error_handler)

        # Start the Bot
        logger.info("Starting bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.critical(f"Failed to start the bot: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()