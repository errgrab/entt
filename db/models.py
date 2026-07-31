import datetime

from peewee import (
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    Model,
    TextField,
)

from db.database import db


class BaseModel(Model):
    class Meta:
        database = db


class Setting(BaseModel):
    key = CharField(primary_key=True)
    value = TextField()


class Wallet(BaseModel):
    id = IntegerField(primary_key=True)
    name = CharField(unique=True)
    balance_cents = IntegerField()


class Tag(BaseModel):
    name = CharField(unique=True)


class TransactionType(BaseModel):
    name = CharField(unique=True)


class Transaction(BaseModel):
    id = IntegerField(primary_key=True)
    title = CharField()
    description = TextField(null=True)
    value_cents = IntegerField()
    wallet = ForeignKeyField(Wallet, backref="transactions")
    ts_type = ForeignKeyField(TransactionType, backref="transactions")
    timestamp = DateTimeField(default=datetime.datetime.now)


class Task(BaseModel):
    id = IntegerField(primary_key=True)
    title = CharField()
    description = TextField(null=True)
    completed = BooleanField(default=False)
    deadline = DateTimeField(null=True)
    created_at = DateTimeField(default=datetime.datetime.now)
    completed_at = DateTimeField(null=True)


class Note(BaseModel):
    id = IntegerField(primary_key=True)
    title = CharField()
    content = TextField()
    created_at = DateTimeField(default=datetime.datetime.now)
    updated_at = DateTimeField(default=datetime.datetime.now)


class TransactionTag(BaseModel):
    transaction = ForeignKeyField(Transaction, backref="transaction_tag")
    tag = ForeignKeyField(Tag, backref="transaction_tag")

    class Meta:
        indexes = ((("transaction", "tag"), True),)


class NoteTag(BaseModel):
    note = ForeignKeyField(Note, backref="note_tag")
    tag = ForeignKeyField(Tag, backref="note_tag")

    class Meta:
        indexes = ((("note", "tag"), True),)
