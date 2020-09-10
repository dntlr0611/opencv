#!/usr/bin/env python3

import telegram
from telegram.ext import Updater
from telegram.ext import CommandHandler
from telegram.ext import MessageHandler, Filters
from telegram.error import (TelegramError, Unauthorized, BadRequest,
                            TimedOut, ChatMigrated, NetworkError)
import logging
import person_db
import face_classifier
import io
import cv2


class CmdDefault():
    def __init__(self, telegram_bot, name=None):
        if name is None:
            name = self.__class__.__name__[3:].lower()
        self.name = name
        self.tb = telegram_bot

    def usage(self):
        return '/' + self.name

    def method(self, update, context):
        # dummy method - echo
        chat_id = update.effective_chat.id
        reply = update.message.text
        context.bot.send_message(chat_id=chat_id, text=reply)


class CmdName(CmdDefault):
    def usage(self):
        return '/' + self.name + ' old_name new_name'

    def method(self, update, context):
        chat_id = update.effective_chat.id
        args = update.message.text.split()
        if len(args) == 3:
            if self.tb.pdb.rename(args[1], args[2]) == 0:
                reply = 'Name changed: ' + args[1] + ' -> ' + args[2]
            else:
                reply = 'Cannot change the person with name ' + args[1]
        else:
            reply = 'usage: ' + self.usage()
        context.bot.send_message(chat_id=chat_id, text=reply)

class CmdList(CmdDefault):
    def method(self, update, context):
        chat_id = update.effective_chat.id
        if len(self.tb.pdb.persons) == 0:
            reply = 'No persons in DB'
            context.bot.send_message(chat_id=chat_id, text=reply)
            return
        for person in self.tb.pdb.persons:
            reply = "%s with %d faces" % (person.name, len(person.faces))
            image = person.get_random_montage()
            is_success, buf = cv2.imencode(".jpg", image)
            bio = io.BytesIO(buf)
            bio.seek(0)
            context.bot.send_photo(chat_id=chat_id, photo=bio, caption=reply)

class CmdStatus(CmdDefault):
    def method(self, update, context):
        chat_id = update.effective_chat.id
        reply = 'In person DB, ' + self.tb.pdb.__repr__()
        reply += '\n' + self.tb.fc.status_string
        if self.tb.fc.running is True:
            reply += '\n' + self.tb.fc.source_info_string
        context.bot.send_message(chat_id=chat_id, text=reply)

class CmdStart(CmdDefault):
    def method(self, update, context):
        chat_id = update.effective_chat.id
        if self.tb.fc.running:
            reply = 'Face classifier is running.'
        else:
            self.tb.fc.start_running()
            reply = 'OK. Face classifier is started.'
        reply += '\n' + self.tb.fc.source_info_string
        if chat_id != self.tb.alarm_receiver:
            reply += '\nVisitor alarm will be sent to you'
            reply += ' (' + str(chat_id) + ').'
            self.tb.alarm_receiver = chat_id
        reply += '\n' + 'To stop face classifier, use command /stop.'
        context.bot.send_message(chat_id=chat_id, text=reply)

class CmdStop(CmdDefault):
    def method(self, update, context):
        chat_id = update.effective_chat.id
        reply = self.tb.fc.settings.__repr__()
        if self.tb.fc.running:
            self.tb.alarm_receiver = None
            reply = 'OK. Stop face classifier.'
            self.tb.fc.stop_running()
        else:
            reply = 'Face classifier is not running now.'
        context.bot.send_message(chat_id=chat_id, text=reply)

class CmdSettings(CmdDefault):
    def method(self, update, context):
        chat_id = update.effective_chat.id
        reply = self.tb.fc.settings.__repr__()
        context.bot.send_message(chat_id=chat_id, text=reply)

class CmdShot(CmdDefault):
    def method(self, update, context):
        chat_id = update.effective_chat.id
        if self.tb.fc.running:
            image = self.tb.fc.last_frame
            is_success, buf = cv2.imencode(".jpg", image)
            bio = io.BytesIO(buf)
            bio.seek(0)
            context.bot.send_photo(chat_id=chat_id, photo=bio)
        else:
            reply = 'Face classifier is not running now.'
            context.bot.send_message(chat_id=chat_id, text=reply)

class CmdHelp(CmdDefault):
    def method(self, update, context):
        chat_id = update.effective_chat.id
        usages = [cmd.usage() for cmd in self.tb.commands]
        reply = '\n'.join(usages)
        context.bot.send_message(chat_id=chat_id, text=reply)


class VisitorAlarm():
    def __init__(self, token, face_classifier=None, person_db=None):
        logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

        self.token = token
        self.core = telegram.Bot(token)
        self.updater = Updater(token=token, use_context=True)

        self.fc = face_classifier
        self.fc.set_on_new_person(self.on_new_person)
        self.pdb = person_db
        self.alarm_receiver = None

        #self.usages = []
        self.commands = []
        self.add_command(CmdHelp(self))
        self.add_command(CmdSettings(self))
        self.add_command(CmdStart(self))
        self.add_command(CmdStop(self))
        self.add_command(CmdStatus(self))
        self.add_command(CmdShot(self))
        self.add_command(CmdName(self))
        self.add_command(CmdList(self))

        # unknown handler should be added last
        handler = MessageHandler(Filters.command, self.unknown)
        self.updater.dispatcher.add_handler(handler)

        handler = MessageHandler(Filters.text & (~Filters.command), self.unknown)
        self.updater.dispatcher.add_handler(handler)

        # error handler
        self.updater.dispatcher.add_error_handler(self.error_callback)

    def add_command(self, handlerObj):
        self.commands.append(handlerObj)
        handler = CommandHandler(handlerObj.name, handlerObj.method)
        self.updater.dispatcher.add_handler(handler)

    # error handler
    # https://github.com/python-telegram-bot/python-telegram-bot/wiki/Exception-Handling
    def error_callback(self, update, context):
        try:
            raise context.error
        except Unauthorized:
            # remove update.message.chat_id from conversation list
            print("Unauthorized error")
        except BadRequest:
            # handle malformed requests
            print("BadRequest error")
        except TimedOut:
            # handle slow connection problems
            print("TimedOut error")
        except NetworkError:
            # handle other connection problems
            print("NetworkError error")
        except ChatMigrated as e:
            # the chat_id of a group has changed, use e.new_chat_id instead
            print("ChatMigrated error")
        except TelegramError:
            # handle all other telegram related errors
            print("TelegramError error")

    def start_polling(self):
        self.updater.start_polling()

    def stop(self):
        self.updater.stop()

    def idle(self):
        self.updater.idle()

    def unknown(self, update, context):
        chat_id = update.effective_chat.id
        reply = "Sorry, I didn't understand that command."
        reply += "\nTry /help for available commands."
        context.bot.send_message(chat_id=chat_id, text=reply)

    def on_new_person(self, person):
        chat_id = self.alarm_receiver
        reply = "new person %s" % person.name
        image = person.get_montage_2()
        is_success, buf = cv2.imencode(".jpg", image)
        bio = io.BytesIO(buf)
        bio.seek(0)
        self.core.send_photo(chat_id=chat_id, photo=bio, caption=reply)
        print(reply)


if __name__ == '__main__':
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True,
                    help="Telegram Bot Token")
    ap.add_argument("--srcfile", type=str, default='0',
                    help="Video file to process. If not specified, web cam is used.")
    args = ap.parse_args()

    dir_name = "result"
    pdb = person_db.PersonDB()
    pdb.load_db()

    settings = face_classifier.Settings()
    settings.source_file = args.srcfile
    fc = face_classifier.FaceClassifier(pdb, settings)

    bot = VisitorAlarm(args.token, face_classifier=fc, person_db=pdb)
    bot.start_polling()
    print("telegram bot with token", args.token)
    print("press ^C to stop...")
    bot.idle()
    fc.stop_running()
    print("telegram bot finished")
