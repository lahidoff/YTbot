import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import yt_dlp
import json
import aiohttp

# Токен от BotFather
TOKEN = "7990130815:AAG1wTiqzhZq--pFM4jZZ6zv5bdm6_Pbk0w"

# Инициализация бота (без сессии на верхнем уровне)
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Состояния для FSM
class UserState(StatesGroup):
    waiting_for_link = State()
    waiting_for_auth_code = State()

# Путь к файлу Google API
CLIENT_SECRETS_FILE = "certs.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
youtube = None
user_tokens = {}
user_video_lists = {}
user_current_video = {}

# Главное меню
async def main_menu(chat_id):
    buttons = []
    if chat_id in user_tokens:
        buttons.append([types.KeyboardButton(text="YouTube"), types.KeyboardButton(text="Вставить ссылку на видео")])
    else:
        buttons.append([types.KeyboardButton(text="Авторизоваться через Google"), types.KeyboardButton(text="Вставить ссылку на видео")])
    keyboard = types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    return keyboard

# Команда /start
@dp.message(Command(commands=['start']))
async def send_welcome(message: types.Message):
    await message.answer("Привет! Я бот для просмотра YouTube в Telegram.\nВыбери действие:", 
                         reply_markup=await main_menu(message.chat.id))

# Авторизация через Google
@dp.message(lambda message: message.text == "Авторизоваться через Google")
async def start_auth(message: types.Message):
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    auth_url, _ = flow.authorization_url(prompt="consent")
    await message.answer(f"Перейди по ссылке и авторизуйся:\n{auth_url}\nПосле вставь код сюда.")
    await UserState.waiting_for_auth_code.set()

# Обработка кода авторизации
@dp.message(StateFilter(UserState.waiting_for_auth_code))
async def process_auth_code(message: types.Message, state: FSMContext):
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    flow.fetch_token(code=message.text)
    credentials = flow.credentials
    user_tokens[message.chat.id] = credentials.to_json()
    global youtube
    youtube = build("youtube", "v3", credentials=credentials)
    await message.answer("Авторизация прошла успешно!", reply_markup=await main_menu(message.chat.id))
    await state.finish()

# Меню YouTube после авторизации
@dp.message(lambda message: message.text == "YouTube")
async def youtube_menu(message: types.Message):
    buttons = [
        [types.KeyboardButton(text="Лента YouTube"), types.KeyboardButton(text="YouTube Shorts"), types.KeyboardButton(text="Рекомендации")],
        [types.KeyboardButton(text="Смотреть позже"), types.KeyboardButton(text="Настройки качества")],
        [types.KeyboardButton(text="Вернуться в главное меню")]
    ]
    keyboard = types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await message.answer("Выбери раздел:", reply_markup=keyboard)

# Лента YouTube (по 3 видео)
@dp.message(lambda message: message.text == "Лента YouTube")
async def youtube_feed(message: types.Message):
    chat_id = message.chat.id
    if chat_id not in user_tokens:
        await message.answer("Сначала авторизуйся через Google!")
        return

    request = youtube.search().list(
        part="id",
        forMine=True,
        type="video",
        maxResults=15
    )
    response = request.execute()
    video_ids = [item["id"]["videoId"] for item in response["items"]]
    video_urls = [f"https://www.youtube.com/watch?v={vid}" for vid in video_ids]

    user_video_lists[chat_id] = video_urls
    user_current_video[chat_id] = {"index": 0, "type": "feed", "video_msg_ids": []}
    await send_feed_videos(chat_id, 0)

# YouTube Shorts
@dp.message(lambda message: message.text == "YouTube Shorts")
async def youtube_shorts(message: types.Message):
    chat_id = message.chat.id
    if chat_id not in user_tokens:
        await message.answer("Сначала авторизуйся через Google!")
        return

    request = youtube.search().list(
        part="id",
        q="shorts",
        type="video",
        videoDuration="short",
        maxResults=10
    )
    response = request.execute()
    video_ids = [item["id"]["videoId"] for item in response["items"]]
    video_urls = [f"https://www.youtube.com/watch?v={vid}" for vid in video_ids]

    user_video_lists[chat_id] = video_urls
    user_current_video[chat_id] = {"index": 0, "type": "shorts"}
    await send_video(chat_id, video_urls[0])

# Рекомендации
@dp.message(lambda message: message.text == "Рекомендации")
async def youtube_recommendations(message: types.Message):
    chat_id = message.chat.id
    if chat_id not in user_tokens:
        await message.answer("Сначала авторизуйся через Google!")
        return

    request = youtube.videos().list(
        part="id",
        chart="mostPopular",
        maxResults=10
    )
    response = request.execute()
    video_ids = [item["id"] for item in response["items"]]
    video_urls = [f"https://www.youtube.com/watch?v={vid}" for vid in video_ids]

    user_video_lists[chat_id] = video_urls
    user_current_video[chat_id] = {"index": 0, "type": "recommendations"}
    await send_video(chat_id, video_urls[0])

# Смотреть позже
@dp.message(lambda message: message.text == "Смотреть позже")
async def watch_later(message: types.Message):
    chat_id = message.chat.id
    if chat_id not in user_tokens:
        await message.answer("Сначала авторизуйся через Google!")
        return

    request = youtube.playlists().list(
        part="id",
        mine=True
    )
    response = request.execute()
    watch_later_playlist_id = None
    for playlist in response["items"]:
        if playlist["id"].startswith("WL"):
            watch_later_playlist_id = playlist["id"]
            break

    if not watch_later_playlist_id:
        await message.answer("Плейлист 'Смотреть позже' не найден!")
        return

    request = youtube.playlistItems().list(
        part="contentDetails",
        playlistId=watch_later_playlist_id,
        maxResults=10
    )
    response = request.execute()
    video_ids = [item["contentDetails"]["videoId"] for item in response["items"]]
    video_urls = [f"https://www.youtube.com/watch?v={vid}" for vid in video_ids]

    user_video_lists[chat_id] = video_urls
    user_current_video[chat_id] = {"index": 0, "type": "watch_later"}
    await send_video(chat_id, video_urls[0])

# Вставить ссылку
@dp.message(lambda message: message.text == "Вставить ссылку на видео")
async def ask_for_link(message: types.Message):
    await message.answer("Вставь ссылку на видео с YouTube:")
    await UserState.waiting_for_link.set()

# Скачивание и отправка одного видео
async def send_video(chat_id, video_url, message_id=None):
    ydl_opts = {
        "format": "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "outtmpl": "video.mp4",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])
    
    if chat_id in user_current_video and "video_msg_id" in user_current_video[chat_id]:
        await bot.delete_message(chat_id, user_current_video[chat_id]["video_msg_id"])

    with open("video.mp4", "rb") as video:
        video_msg = await bot.send_video(chat_id, video)
    os.remove("video.mp4")

    keyboard = types.InlineKeyboardMarkup()
    current_index = user_current_video[chat_id]["index"]
    video_list = user_video_lists[chat_id]
    
    if current_index > 0:
        keyboard.add(types.InlineKeyboardButton("◀️", callback_data=f"prev_{chat_id}"))
    if current_index < len(video_list) - 1:
        keyboard.add(types.InlineKeyboardButton("▶️", callback_data=f"next_{chat_id}"))

    if message_id:
        await bot.edit_message_reply_markup(chat_id, message_id, reply_markup=keyboard)
    else:
        buttons_msg = await bot.send_message(chat_id, "Навигация:", reply_markup=keyboard)
        user_current_video[chat_id]["video_msg_id"] = video_msg.message_id
        user_current_video[chat_id]["buttons_msg_id"] = buttons_msg.message_id

# Скачивание и отправка трёх видео
async def send_feed_videos(chat_id, start_index):
    video_list = user_video_lists[chat_id]
    end_index = min(start_index + 3, len(video_list))
    video_urls = video_list[start_index:end_index]

    if "video_msg_ids" in user_current_video[chat_id]:
        for msg_id in user_current_video[chat_id]["video_msg_ids"]:
            await bot.delete_message(chat_id, msg_id)

    video_msg_ids = []
    for url in video_urls:
        ydl_opts = {
            "format": "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "outtmpl": "video.mp4",
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        with open("video.mp4", "rb") as video:
            video_msg = await bot.send_video(chat_id, video)
        os.remove("video.mp4")
        video_msg_ids.append(video_msg.message_id)

    keyboard = types.InlineKeyboardMarkup()
    if start_index > 0:
        keyboard.add(types.InlineKeyboardButton("◀️", callback_data=f"feed_prev_{chat_id}"))
    if end_index < len(video_list):
        keyboard.add(types.InlineKeyboardButton("▶️", callback_data=f"feed_next_{chat_id}"))

    if "buttons_msg_id" in user_current_video[chat_id]:
        await bot.edit_message_reply_markup(chat_id, user_current_video[chat_id]["buttons_msg_id"], reply_markup=keyboard)
    else:
        buttons_msg = await bot.send_message(chat_id, "Навигация:", reply_markup=keyboard)
        user_current_video[chat_id]["buttons_msg_id"] = buttons_msg.message_id

    user_current_video[chat_id]["index"] = start_index
    user_current_video[chat_id]["video_msg_ids"] = video_msg_ids

# Обработка ссылки
@dp.message(StateFilter(UserState.waiting_for_link))
async def process_link(message: types.Message, state: FSMContext):
    url = message.text
    chat_id = message.chat.id
    if chat_id not in user_video_lists:
        user_video_lists[chat_id] = []
    user_video_lists[chat_id].append(url)
    user_current_video[chat_id] = {"index": 0, "type": "link"}
    await send_video(chat_id, url)
    await state.finish()

# Обработка кнопок для одиночных видео
@dp.callback_query(lambda c: c.data.startswith("prev_") or c.data.startswith("next_"))
async def process_callback(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    action = callback_query.data.split("_")[0]
    current_index = user_current_video[chat_id]["index"]
    video_list = user_video_lists[chat_id]
    
    if action == "prev" and current_index > 0:
        current_index -= 1
    elif action == "next" and current_index < len(video_list) - 1:
        current_index += 1
    
    user_current_video[chat_id]["index"] = current_index
    await send_video(chat_id, video_list[current_index], user_current_video[chat_id]["buttons_msg_id"])
    await callback_query.answer()

# Обработка кнопок для Ленты YouTube
@dp.callback_query(lambda c: c.data.startswith("feed_prev_") or c.data.startswith("feed_next_"))
async def process_feed_callback(callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    action = callback_query.data.split("_")[1]
    current_index = user_current_video[chat_id]["index"]
    
    if action == "prev" and current_index > 0:
        current_index -= 3
    elif action == "next":
        current_index += 3
    
    await send_feed_videos(chat_id, current_index)
    await callback_query.answer()

# Возврат в главное меню
@dp.message(lambda message: message.text == "Вернуться в главное меню")
async def back_to_main(message: types.Message):
    await message.answer("Главное меню:", reply_markup=await main_menu(message.chat.id))

# Асинхронный запуск бота
async def main():
    print("Пытаюсь удалить вебхук...")
    await bot.delete_webhook()
    print("Вебхук удалён, начинаю polling...")
    await dp.start_polling(bot)
    print("Polling завершён")

if __name__ == "__main__":
    asyncio.run(main())