import html
import json
import traceback
import logging
import os
import pymongo
import requests
from bson.objectid import ObjectId
from typing import Optional, Tuple
from urllib.request import urlopen
from telegram import Update, ReplyKeyboardMarkup, ChatMemberUpdated, ChatMember, Chat, InlineKeyboardButton, \
    InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.ext import (Application, ConversationHandler, CommandHandler,
                          MessageHandler, filters, PicklePersistence, AIORateLimiter, ChatMemberHandler, ContextTypes,
                          CallbackQueryHandler)

# ------------------------------------ CONSTANTS -----------------------------------------------------------------------
logging.basicConfig(
    # filename='syccbot.log',
    # format="[%(asctime)s %(levelname)s] %(message)s",
    format="[%(levelname)s] %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

DEVELOPER_CHAT_ID = os.environ['DEVELOPER_CHAT_ID']
url = os.environ['GLOT_URL']

headers = {
    'Authorization': os.environ['GLOT_AUTHORIZATION'],
    'Content-type': 'application/json'
}

myclient = pymongo.MongoClient("mongodb://localhost:27017/")
mydb = myclient["code_checker"]
chats_col = mydb["chats"]
users_col = mydb["users"]
tasks_col = mydb["tasks"]

(
    MAIN_MENU,
    TASKS,
    CHOOSE_LEVEL,
    TASK_SELECTED,
    TEST_CODE,
) = range(5)


# -----------------------------------------------HELPERS----------------------------------------------------------------
def mongodb_task_init():
    list_of_cols = mydb.list_collection_names()
    if "tasks" not in list_of_cols:
        task_dict = {
            '_id': 1,
            'level': 1,
            'title': 'Multiply',
            'description': 'Write function to multiply two numbers and return result',
            'tags': ['*'],
            'test_file': '64b3714da4f8394ab18d5caa.py'
        }
        tasks_col.insert_one(task_dict)
        logger.info("added task to db")


def extract_status_change(chat_member_update: ChatMemberUpdated) -> Optional[Tuple[bool, bool]]:
    """Takes a ChatMemberUpdated instance and extracts whether the 'old_chat_member' was a member
    of the chat and whether the 'new_chat_member' is a member of the chat. Returns None, if
    the status didn't change.
    """
    status_change = chat_member_update.difference().get("status")
    old_is_member, new_is_member = chat_member_update.difference().get("is_member",
                                                                       (None, None))

    if status_change is None:
        return None

    old_status, new_status = status_change
    was_member = old_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (old_status == ChatMember.RESTRICTED and old_is_member is True)
    is_member = new_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (new_status == ChatMember.RESTRICTED and new_is_member is True)

    return was_member, is_member


# ----------------------------------------------START-------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat = update.message.chat
    user = update.message.from_user

    logger.info(f'/start command from {chat.first_name} {chat.last_name}')

    context.bot_data.setdefault('chat_ids', set()).add(chat.id)
    context.bot_data.setdefault('user_ids', set()).add(user.id)

    await update.message.reply_text("Welcome to the code checker bot!")

    return await main_menu(update, context)


# ----------------------------------------------MAIN MENU---------------------------------------------------------------
async def main_menu(update: Update, _) -> int:
    buttons = [
        [InlineKeyboardButton('Tasks', callback_data=str(TASKS))],
        [InlineKeyboardButton('blank', callback_data=123)],
        [InlineKeyboardButton('blank', callback_data=321)]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(text="Main menu:", reply_markup=reply_markup)

    return MAIN_MENU


# ----------------------------------------------TASKS-------------------------------------------------------------------
async def choose_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['offset'] = 0

    levels = [['1'], ['2'], ['3']]
    keyboard = ReplyKeyboardMarkup(levels, one_time_keyboard=True)

    await update.message.reply_text(text="choose level", reply_markup=keyboard)

    return CHOOSE_LEVEL


async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # await context.bot.send_message(update.message.chat_id, 'a', reply_markup=ReplyKeyboardRemove())
    level = int(update.message.text)
    offset = context.user_data['offset']

    tasks_list = tasks_col.find({'level': level}).skip(offset).limit(10)

    buttons = []
    for i, task in enumerate(tasks_list, offset + 1):
        buttons.append([InlineKeyboardButton('{}. {}'.format(i, task['title']), callback_data=str(task['_id']))])

    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(text="choose task", reply_markup=reply_markup)

    return TASKS


async def task_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    task_id = query.data
    context.chat_data['task_id'] = task_id

    task = tasks_col.find_one({'_id': ObjectId(task_id)})

    text = 'task #{}\n{}\n{}\n\nPaste python code or send .py file'.format(
        task['_id'], task['title'], task['description'])

    buttons = [['Back']]
    keyboard = ReplyKeyboardMarkup(buttons)

    await query.edit_message_text(
        text=text
    )

    return TASK_SELECTED


async def send_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    main_str = ''

    if update.message.text:
        msg_text = update.message.text
        main_str = msg_text

    if update.message.document:
        file_tg = await context.bot.get_file(update.message.document.file_id)
        file = urlopen(file_tg.file_path)
        for line in file:
            main_str += line.decode('utf-8')

    unit_test_str = ''
    with open('test_files/{}.py'.format(context.chat_data['task_id']), "r") as test_f:
        unit_test_str += test_f.read()

    logger.info(f'code from user:\n{main_str}')
    logger.info(f'unit tests:\n{unit_test_str}')

    data = {
        "files": [
            {"name": "unit_tests.py", "content": unit_test_str},
            {"name": "user_code.py", "content": main_str}
        ]
    }

    x = requests.post(url, json=data, headers=headers)

    logger.info(f'result from glot:\n{x.json()}')

    text = x.json()

    await update.message.reply_text(text=text)

    return TEST_CODE


# ----------------------------------------------CHAT MEMBERS TRACKER----------------------------------------------------

async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tracks the chats the bot is in."""
    result = extract_status_change(update.my_chat_member)
    if result is None:
        return
    was_member, is_member = result

    # Let's check who is responsible for the change
    cause_name = update.effective_user.full_name

    # Handle chat types differently:
    chat = update.effective_chat
    if chat.type == Chat.PRIVATE:
        if not was_member and is_member:
            # This may not be really needed in practice because most clients will automatically
            # send a /start command after the user unblocks the bot, and start_private_chat()
            # will add the user to "user_ids".
            # We're including this here for the sake of the example.
            logger.info("%s unblocked the bot", cause_name)
            context.bot_data.setdefault("user_ids", set()).add(chat.id)
        elif was_member and not is_member:
            logger.info("%s blocked the bot", cause_name)
            context.bot_data.setdefault("user_ids", set()).discard(chat.id)
    elif chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
        if not was_member and is_member:
            logger.info("%s added the bot to the group %s",
                        cause_name, chat.title)
            context.bot_data.setdefault("group_ids", set()).add(chat.id)
        elif was_member and not is_member:
            logger.info("%s removed the bot from the group %s",
                        cause_name, chat.title)
            context.bot_data.setdefault("group_ids", set()).discard(chat.id)
    elif not was_member and is_member:
        logger.info("%s added the bot to the channel %s",
                    cause_name, chat.title)
        context.bot_data.setdefault("channel_ids", set()).add(chat.id)
    elif was_member and not is_member:
        logger.info("%s removed the bot from the channel %s",
                    cause_name, chat.title)
        context.bot_data.setdefault("channel_ids", set()).discard(chat.id)


async def show_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)

    if chat_id == DEVELOPER_CHAT_ID:
        """Shows which chats the bot is in"""
        user_ids = ", ".join(str(uid)
                             for uid in context.bot_data.setdefault("user_ids", set()))
        group_ids = ", ".join(str(gid)
                              for gid in context.bot_data.setdefault("group_ids", set()))
        channel_ids = ", ".join(
            str(cid) for cid in context.bot_data.setdefault("channel_ids", set()))
        text = (
            f"@{context.bot.username} is currently in a conversation with the user IDs {user_ids}."
            f" Moreover it is a member of the groups with IDs {group_ids} "
            f"and administrator in the channels with IDs {channel_ids}."
        )
        await update.effective_message.reply_text(text)

    else:
        await update.effective_message.reply_text('Sorry, I do not know this command')


# -----------------------------------------ERROR HANDLER----------------------------------------------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

    tb_list = traceback.format_exception(
        None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f"An exception was raised while handling an update\n"
        f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
        "</pre>\n\n"
        f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
        f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )

    await context.bot.send_message(
        chat_id=DEVELOPER_CHAT_ID, text=message, parse_mode=ParseMode.HTML
    )


def main() -> None:
    persistence = PicklePersistence(filepath='persistence.pickle')

    app = Application.builder().token(os.environ['TOKEN']).rate_limiter(
        AIORateLimiter()).persistence(persistence).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                MessageHandler(filters.Regex("^Tasks$"), tasks)
            ],
            CHOOSE_LEVEL: [
                # MessageHandler(filters.Regex("^[123]$"), tasks)
            ],
            TASKS: [
                # CallbackQueryHandler(task_selected)
                # MessageHandler(filters.TEXT & ~filters.COMMAND, task_selected)
            ],
            TASK_SELECTED: [
                # MessageHandler(filters.TEXT | filters.Document.PY &
                #                ~filters.COMMAND, send_code)
            ]
        },
        fallbacks=[CommandHandler('menu', main_menu)],
        persistent=True,
        name='main_conversation',
    )

    app.add_handler(conv_handler)

    app.add_handler(ChatMemberHandler(
        track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CommandHandler("show_chats", show_chats))
    app.add_error_handler(error_handler)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()