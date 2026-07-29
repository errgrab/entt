import os
import datetime
import discord
from peewee import *

# Discord
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
finance_channel = 1509873835657269279


# Discord functions
@client.event
async def on_ready():
    print("[entt] discord bot is up.")


@client.event
async def on_message(msg):
    if msg.author == client.user:
        return
    if msg.channel.id != finance_channel:
        return
    if msg.content.startswith("!"):
        if msg.content == "!ping":
            await msg.channel.send("pong!")
        pass # TODO parsing commands for configuration like adding tags and transaction types.


# peewee
db_file = 'app.db'
db = SqliteDatabase(db_file)


# peewee SQL tables
class Table(Model):
    class Meta:
        database = db


class Setting(Table):
    key = CharField(primary_key=True)
    value = TextField()


class Wallet(Table):
    name = CharField(unique=True)
    balance_cents = IntegerField()
    description = TextField(null=True)


class Tag(Table):
    name = CharField(unique=True)


class TransactionType(Table):
    name = CharField(unique=True)


class Transaction(Table):
    title = CharField()
    description = TextField(null=True)
    value_cents = IntegerField()
    wallet = ForeignKeyField(Wallet, backref='transactions')
    transaction_type = ForeignKeyField(TransactionType, backref='transactions')
    timestamp = DateTimeField(default=datetime.datetime.now)


class Task(Table):
    title = CharField()
    description = TextField(null=True)
    completed = BooleanField(default=False)
    deadline = DateTimeField(null=True)
    created_at = DateTimeField(default=datetime.datetime.now)
    completed_at = DateTimeField(null=True)


class Note(Table):
    title = CharField()
    content = TextField()
    created_at = DateTimeField(default=datetime.datetime.now)
    updated_at = DateTimeField(default=datetime.datetime.now)


class TransactionTag(Table):
    transaction = ForeignKeyField(Transaction, backref='transaction_tags')
    tag = ForeignKeyField(Tag, backref='transaction_tags')


class NoteTag(Table):
    note = ForeignKeyField(Note, backref='note_tags')
    tag = ForeignKeyField(Tag, backref='note_tags')


# peewee functions
def get_setting(key):
    return Setting.get_by_id(key).value


def set_setting(key, value):
    Setting.replace(key=key, value=value).execute()


def bootstrap():
    if os.path.exists(db_file):
        return
    print("[entt] Bootstraping...")
    with db:
        db.create_tables([
            Setting, Wallet, Tag, TransactionType, Transaction, Task, Note,
            TransactionTag, NoteTag,
        ])
        print("[entt] Discord token necessary...")
        token = input("discord_token: ")
        Setting.create(key="discord_token", value=token)


# Main
def main():
    token = Setting.get(Setting.key == "discord_token").value
    client.run(token)


if __name__ == '__main__':
    bootstrap()
    main()
