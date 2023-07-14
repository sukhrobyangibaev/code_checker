import logging

import pymongo as pymongo

# logging.basicConfig(
#     # filename='syccbot.log',
#     format="[%(asctime)s > %(levelname)s > %(name)s] %(message)s",
#     level=logging.INFO
# )
# logger = logging.getLogger(__name__)


myclient = pymongo.MongoClient("mongodb://localhost:27017/")
mydb = myclient["code_checker"]
chats_col = mydb["chats"]
users_col = mydb["users"]
tasks_col = mydb["tasks"]


MAIN_MENU = 1
TASKS = 11
TASK_SELECTED = 111
TEST_CODE = 1111