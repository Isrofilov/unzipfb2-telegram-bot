import os
import requests
import tempfile
import zipfile
import shutil
from telegram import Update, InputFile
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters
from lxml import etree

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALLOWED_FILE_SIZE = 32 * 1024 * 1024  # 32 MB in bytes
MAX_FILES_IN_ARCHIVE = 1  # Maximum number of files in archive

def get_file_path(file_id):
    try:
        response = requests.get(f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={file_id}")
        response.raise_for_status()
        result = response.json()
        return f"https://api.telegram.org/file/bot{TOKEN}/{result['result']['file_path']}"
    except requests.RequestException as e:
        print(f"Error fetching file path: {e}")
        return None

async def send_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    await update.message.reply_text(text)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    file_id = document.file_id
    file_size = document.file_size

    if file_size > ALLOWED_FILE_SIZE:
        await send_reply(update, context, 'The file exceeds the allowed size of 32 MB.')
        return

    file_url = get_file_path(file_id)
    if not file_url:
        await send_reply(update, context, 'Failed to retrieve the file. Please try again.')
        return

    response = requests.get(file_url, stream=True)
    response.raise_for_status()
    
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        for chunk in response.iter_content(chunk_size=8192):
            tmp.write(chunk)
        tmp_path = tmp.name

    with tempfile.TemporaryDirectory() as extract_path:
        try:
            with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
                if len(zip_ref.infolist()) > MAX_FILES_IN_ARCHIVE:
                    await send_reply(update, context, f'The archive contains more than {MAX_FILES_IN_ARCHIVE} files, which is not allowed.')
                    os.remove(tmp_path)
                    return

                total_uncompressed_size = sum(zinfo.file_size for zinfo in zip_ref.infolist())
                if total_uncompressed_size > ALLOWED_FILE_SIZE:
                    await send_reply(update, context, 'The total uncompressed size of the archive exceeds the allowed limit of 100 MB.')
                    os.remove(tmp_path)
                    return

                zip_ref.extractall(extract_path)
        except zipfile.BadZipFile:
            await send_reply(update, context, 'The file is not a valid zip archive.')
            os.remove(tmp_path)
            return

        fb2_found = False
        for root, _, files in os.walk(extract_path):
            for file in files:
                if file.endswith('.fb2'):
                    fb2_path = os.path.join(root, file)
                    if os.path.getsize(fb2_path) <= ALLOWED_FILE_SIZE:
                        with open(fb2_path, 'rb') as fb2_file:
                            try:
                                tree = etree.parse(fb2_file)
                                ns = {'fb': 'http://www.gribuser.ru/xml/fictionbook/2.0'}
                                book_title = tree.findtext('.//fb:book-title', namespaces=ns)
                                if book_title:
                                    caption = f'Your .fb2 file "{book_title}" has been successfully extracted from the archive! 📚 Enjoy reading!'
                                else:
                                    caption = 'Your .fb2 file has been successfully extracted from the archive! 📚 Enjoy reading!'
                            except Exception:
                                caption = 'Your .fb2 file has been successfully extracted from the archive! 📚 Enjoy reading!'
                            
                            fb2_file.seek(0)
                            await update.message.reply_document(
                                document=InputFile(fb2_file),
                                caption=caption
                            )
                        fb2_found = True
                    else:
                        await send_reply(update, context, 'The extracted .fb2 file exceeds the allowed size of 32 MB.')
                    break
            if fb2_found:
                break

        if not fb2_found:
            await send_reply(update, context, 'No valid .fb2 file found in the archive.')

    os.remove(tmp_path)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_reply(update, context, 'Welcome to the Unzip Bot! 🤖\nI\'m here to help you extract .fb2 files from zip archives. Just send me a zip file, and I\'ll handle the rest. If there are multiple .fb2 files, I\'ll extract the first one I find.')

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_reply(update, context, 'Just send me a zip file, and I\'ll handle the rest.')

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    document_handler = MessageHandler(filters.Document.ALL, handle_document)
    start_handler = CommandHandler('start', start)
    text_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)

    application.add_handler(document_handler)
    application.add_handler(start_handler)
    application.add_handler(text_handler)

    application.run_polling()

if __name__ == "__main__":
    main()
