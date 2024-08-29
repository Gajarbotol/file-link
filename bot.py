import os
import math
import sqlite3
import requests
from telegram import Update, Bot
from telegram.constants import ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackContext, ConversationHandler
from telegram.ext.filters import TEXT  # Updated import for Filters

# Replace with your bot token
BOT_TOKEN = '7448594075:AAFMCpeHgz1sjE7LgN0XMyPW14Bz8x2qab8'
CHUNK_SIZE = 49 * 1024 * 1024  # 49 MB

LINK, PROCESS = range(2)

# Initialize the in-memory status tracking
status_tracking = {}

# Initialize SQLite database
conn = sqlite3.connect('file_processes.db')
c = conn.cursor()

# Create table if not exists
c.execute('''CREATE TABLE IF NOT EXISTS file_processes
             (chat_id INTEGER, file_name TEXT, status TEXT)''')
conn.commit()

def start(update: Update, context: CallbackContext) -> int:
    update.message.reply_text("Please send me the file link.")
    return LINK

def get_file_link(update: Update, context: CallbackContext) -> int:
    file_url = update.message.text
    chat_id = update.message.chat_id
    context.user_data['file_url'] = file_url

    # Start tracking the status
    status_tracking[chat_id] = "Downloading the file..."

    # Store initial status in the database
    c.execute("INSERT INTO file_processes (chat_id, file_name, status) VALUES (?, ?, ?)",
              (chat_id, file_url.split('/')[-1], status_tracking[chat_id]))
    conn.commit()

    message = update.message.reply_text("Downloading the file, please wait...")
    download_file(file_url, context, message)

    file_size = os.path.getsize(context.user_data['file_path'])
    if file_size > 50 * 1024 * 1024:  # Larger than 50 MB
        status_tracking[chat_id] = "Splitting file into chunks..."
        c.execute("UPDATE file_processes SET status = ? WHERE chat_id = ?", 
                  (status_tracking[chat_id], chat_id))
        conn.commit()

        update.message.reply_text("The file is larger than 50 MB. Splitting it into chunks...")
        chunks = split_file(context.user_data['file_path'], CHUNK_SIZE, message, context)
        send_chunks(context.bot, chat_id, chunks, message)
        cleanup_chunks(chunks)
    else:
        status_tracking[chat_id] = "Sending file..."
        c.execute("UPDATE file_processes SET status = ? WHERE chat_id = ?", 
                  (status_tracking[chat_id], chat_id))
        conn.commit()

        update.message.reply_text("The file is under 50 MB. Sending the file...")
        send_file(context.bot, chat_id, context.user_data['file_path'], message)

    cleanup_file(context.user_data['file_path'])
    
    # Mark process as complete
    status_tracking[chat_id] = "Completed"
    c.execute("UPDATE file_processes SET status = ? WHERE chat_id = ?", 
              (status_tracking[chat_id], chat_id))
    conn.commit()

    return ConversationHandler.END

def download_file(url, context, message):
    local_filename = url.split('/')[-1]
    r = requests.get(url, stream=True)
    total_size = int(r.headers.get('content-length', 0))
    downloaded_size = 0

    with open(local_filename, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded_size += len(chunk)
                update_progress(message, downloaded_size, total_size, "Downloading", context)
                
    context.user_data['file_path'] = local_filename

def split_file(file_path, chunk_size, message, context):
    file_size = os.path.getsize(file_path)
    num_chunks = math.ceil(file_size / chunk_size)
    file_chunks = []

    with open(file_path, 'rb') as f:
        for i in range(num_chunks):
            chunk_data = f.read(chunk_size)
            chunk_file_name = f'{file_path}.part{i+1}'
            with open(chunk_file_name, 'wb') as chunk_file:
                chunk_file.write(chunk_data)
            file_chunks.append(chunk_file_name)
            update_progress(message, i+1, num_chunks, "Splitting", context)

    return file_chunks

def send_chunks(bot, chat_id, chunks, message):
    total_chunks = len(chunks)
    for i, chunk in enumerate(chunks):
        with open(chunk, 'rb') as f:
            bot.send_document(chat_id=chat_id, document=f, caption=f'Part {i+1} of {total_chunks}')
        update_progress(message, i+1, total_chunks, "Sending chunks", None)
    message.edit_text("All chunks sent successfully.")

def send_file(bot, chat_id, file_path, message):
    with open(file_path, 'rb') as f:
        bot.send_document(chat_id=chat_id, document=f)
    message.edit_text("File sent successfully.")

def update_progress(message, current, total, stage, context):
    progress = int((current / total) * 100)
    if context:
        chat_id = message.chat_id
        status_tracking[chat_id] = f"{stage}... {progress}% completed"
        c.execute("UPDATE file_processes SET status = ? WHERE chat_id = ?", 
                  (status_tracking[chat_id], chat_id))
        conn.commit()
    message.edit_text(f"{stage}... {progress}% completed")

def cleanup_chunks(chunks):
    for chunk in chunks:
        os.remove(chunk)

def cleanup_file(file_path):
    os.remove(file_path)

def cancel(update: Update, context: CallbackContext) -> int:
    update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

def check_status(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    if chat_id in status_tracking:
        update.message.reply_text(f"Current status: {status_tracking[chat_id]}")
    else:
        update.message.reply_text("No ongoing tasks found.")

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            LINK: [MessageHandler(TEXT & ~TEXT.command, get_file_link)],  # Updated to use TEXT filter
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    dp.add_handler(conv_handler)
    dp.add_handler(CommandHandler('status', check_status))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
