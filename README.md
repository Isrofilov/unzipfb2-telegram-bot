# unzipfb2-telegram-bot
A Telegram bot that simplifies your reading experience by unzipping archives to extract single FB2 book files. Send a ZIP and get your book ready to read in seconds!

Check it out here: [https://t.me/unzipfb2_bot](https://t.me/unzipfb2_bot)

## Features
- 📚 **Extract FB2 Files**: Automatically extracts FB2 files from ZIP archives.
- 🤖 **Easy to Use**: Just send a ZIP file and receive an FB2 file in return.
- ⏱ **Quick Processing**: Save time with fast extraction and delivery of your book.

### Prerequisites

- Docker
- Docker Compose

### Configuration

To set up the unzipfb2-telegram-bot service, you need to create a `docker-compose.yml` file using the template below. Be sure to replace the placeholder values with your actual configuration details.

    version: '3.8'
    services:
      unzipfb2-telegram-bot:
        image: isrofilov/unzipfb2-telegram-bot:latest
        environment:
          TELEGRAM_BOT_TOKEN: your_telegram_bot_token_here

Here's what you need to replace:

- `your_telegram_bot_token_here`: Replace this with your actual Telegram bot token.

### Running the Bot

To start the unzipfb2-telegram-bot, navigate to the directory containing your `docker-compose.yml` and run:

    docker-compose up -d

Your bot is now running and ready to shorten URLs!

## Usage

1. Send a ZIP archive containing a single FB2 file to the bot.
2. Wait for the bot to process the archive.
3. Receive and download your FB2 file.

Enjoy seamless reading with @unzipfb2_bot – Your personal book unarchiving assistant on Telegram!

## Support

For support, feature requests, or bug reporting, please open an issue on the GitHub repository.