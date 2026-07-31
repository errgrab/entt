import os
from decimal import Decimal

import pytest

# Import your modules
from config import config
from core.db import bootstrap
from core.models import (
    Setting,
    Tag,
    Transaction,
    TransactionTag,
    Wallet,
    db,
)

MODELS = [Setting, Tag, Wallet, Transaction, TransactionTag]


@pytest.fixture(autouse=True)
def setup_test_db():
    """Sets up a clean in-memory database before each test run."""
    # Bind models to the in-memory database
    db.init(":memory:")
    db.connect(reuse_if_open=True)
    db.create_tables(MODELS)

    yield

    db.drop_tables(MODELS)
    db.close()


# -----------------------------------------------------------------------------
# 1. Test Settings
# -----------------------------------------------------------------------------
def test_setting_get_and_set():
    Setting.set_val("theme", "dark")
    assert Setting.get_val("theme") == "dark"

    # Test default fallback
    assert Setting.get_val("non_existent", default="light") == "light"
    assert Setting.get_val("non_existent") == ""


# -----------------------------------------------------------------------------
# 2. Test Tags
# -----------------------------------------------------------------------------
def test_tag_cleaning_and_uniqueness():
    tag1 = Tag.get_or_create_clean("  GROCERIES  ")
    tag2 = Tag.get_or_create_clean("groceries")

    assert tag1.id == tag2.id
    assert tag1.name == "groceries"
    assert Tag.select().count() == 1


# -----------------------------------------------------------------------------
# 3. Test Wallet Balance & Syncing
# -----------------------------------------------------------------------------
def test_wallet_balance_and_sync():
    wallet = Wallet.create(name="Main Bank", balance_cents=0)

    # Test balance property setter
    wallet.balance = "100.50"
    wallet.save()
    assert wallet.balance_cents == 10050
    assert wallet.balance == Decimal("100.50")

    # Add income and outcome transactions
    _ = Transaction.create(
        wallet=wallet,
        name="Salary",
        value_cents=100000,  # $1000.00
        tx_type="income",
    )
    _ = Transaction.create(
        wallet=wallet,
        name="Rent",
        value_cents=40000,  # $400.00
        tx_type="outcome",
    )

    # Test sync_balance calculation
    new_balance = wallet.sync_balance()
    assert new_balance == Decimal("600.00")
    assert wallet.balance_cents == 60000


# -----------------------------------------------------------------------------
# 4. Test Transaction Tagging & Querying
# -----------------------------------------------------------------------------
def test_transaction_tags_and_filtering():
    wallet = Wallet.create(name="Cash", balance_cents=0)
    tx = Transaction(
        wallet=wallet,
        name="Supermarket",
        tx_type="outcome",
        method="credit",
    )
    tx.value = 50.25
    tx.save()

    # Add tags
    tx.add_tag("Food")
    tx.add_tag("Supermarket")

    assert set(tx.tag_names) == {"food", "supermarket"}

    # Filter transactions by tag
    food_txs = list(Transaction.filter_by_tag("food"))
    assert len(food_txs) == 1
    assert food_txs[0].id == tx.id

    # Remove tag
    tx.remove_tag("food")
    assert tx.tag_names == ["supermarket"]


# -----------------------------------------------------------------------------
# 5. Test Transaction Financial Summary
# -----------------------------------------------------------------------------
def test_transaction_summary():
    wallet = Wallet.create(name="Savings", balance_cents=0)

    # Add 2 incomes, 1 outcome
    t1 = Transaction(wallet=wallet, name="Job", tx_type="income")
    t1.value = Decimal("500.00")
    t1.save()

    t2 = Transaction(wallet=wallet, name="Bonus", tx_type="income")
    t2.value = Decimal("150.00")
    t2.save()

    t3 = Transaction(wallet=wallet, name="Dinner", tx_type="outcome")
    t3.value = Decimal("50.00")
    t3.save()

    summary = Transaction.get_summary(wallet_id=wallet.id)
    assert summary["income"] == Decimal("650.00")
    assert summary["outcome"] == Decimal("50.00")
    assert summary["net"] == Decimal("600.00")


# -----------------------------------------------------------------------------
# 6. Test Bootstrap Function
# -----------------------------------------------------------------------------
def test_bootstrap(tmp_path, monkeypatch):
    test_db_path = str(tmp_path / "test_config.db")

    monkeypatch.setitem(config.__dict__, "db_file", test_db_path)
    monkeypatch.setitem(config.__dict__, "finance_channel_id", "123")
    monkeypatch.setitem(config.__dict__, "task_channel_id", "456")
    monkeypatch.setitem(config.__dict__, "note_channel_id", "789")

    db.close()
    db.init(test_db_path)

    # Run bootstrap
    bootstrap()

    assert os.path.exists(test_db_path)
    assert Setting.get_val("finance_channel_id") == "123"
    assert Setting.get_val("task_channel_id") == "456"
    assert Setting.get_val("note_channel_id") == "789"
