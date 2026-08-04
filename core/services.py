from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from peewee import IntegrityError, fn

from core.db import Setting, Tag, Transaction, TransactionTag, Wallet, db

VALID_TX_TYPES = {"income", "outcome"}


class SettingService:
    """Manages application-wide settings with typed getters/setters."""

    SELECTED_WALLET_KEY = "selected_wallet"

    @staticmethod
    def get(key: str, default: str | None = None) -> str:
        return Setting.get_val(key, default)

    @staticmethod
    def set(key: str, value: str) -> None:
        Setting.set_val(key, str(value))


class WalletService:
    """Handles CRUD operations and lookup logic for Wallets."""

    @staticmethod
    def create(name: str, desc: str | None = None) -> Wallet:
        clean_name = name.strip()
        try:
            return Wallet.create(name=clean_name, desc=desc, balance_cents=0)
        except IntegrityError:
            raise ValueError(
                f"Wallet with name '{clean_name}' already exists."
            ) from None

    @staticmethod
    def get(identifier: int | str) -> Wallet | None:
        """Fetches a wallet by ID (int) or name (str, case-insensitive)."""
        if isinstance(identifier, int):
            return Wallet.get_or_none(Wallet.id == identifier)
        if isinstance(identifier, str):
            clean_name = identifier.strip()
            return Wallet.get_or_none(fn.LOWER(Wallet.name) == clean_name.lower())
        raise TypeError(
            f"identifier must be int or str, got {type(identifier).__name__}"
        )

    @staticmethod
    def list(search: str | None = None) -> list[Wallet]:
        """Lists wallets with optional name search filtering."""
        query = Wallet.select()
        if search:
            query = query.where(Wallet.name.contains(search.strip()))
        return list(query.order_by(Wallet.name))

    @staticmethod
    def get_selected() -> Wallet:
        """Fetches the currently selected wallet, or falls back to 'Main Wallet'."""
        selected_name = SettingService.get(SettingService.SELECTED_WALLET_KEY)

        if selected_name:
            wallet = WalletService.get(selected_name)
            if wallet:
                return wallet

        # Fallback: get first existing wallet or create a default "Main Wallet"
        wallet = Wallet.select().first()
        if not wallet:
            wallet = WalletService.create(name="Main Wallet")

        # Sync setting with valid wallet name
        SettingService.set(SettingService.SELECTED_WALLET_KEY, wallet.name)
        return wallet

    @staticmethod
    def select(wallet_name: str) -> Wallet:
        """Marks the given wallet (by name) as the active/selected wallet."""
        wallet = WalletService.get(wallet_name)
        if not wallet:
            raise ValueError(f"Wallet with name '{wallet_name}' does not exist.")

        SettingService.set(SettingService.SELECTED_WALLET_KEY, wallet.name)
        return wallet


class TransactionService:
    """Handles transaction creation, deletion, and advanced filtering."""

    @staticmethod
    def create(
        wallet: Wallet | str,
        name: str,
        value_cents: int,
        tx_type: str = "outcome",
        method: str = "money",
        tags: Iterable[str] = (),
        desc: str | None = None,
    ) -> Transaction:
        """Creates a transaction and syncs wallet balance inside a safe DB transaction."""
        target_wallet = (
            wallet if isinstance(wallet, Wallet) else WalletService.get(wallet)
        )
        if not target_wallet:
            raise ValueError("Target wallet does not exist.")

        if tx_type not in VALID_TX_TYPES:
            raise ValueError(
                f"Invalid tx_type '{tx_type}'. Must be one of {VALID_TX_TYPES}."
            )
        if value_cents <= 0:
            raise ValueError("value_cents must be a positive integer.")

        with db.atomic():
            tx = Transaction.create(
                wallet=target_wallet,
                name=name.strip(),
                desc=desc,
                value_cents=value_cents,
                tx_type=tx_type,
                method=method.strip().lower(),
            )

            for tag_name in tags:
                tx.add_tag(tag_name)

            target_wallet.sync_balance()
            return tx

    @staticmethod
    def get(tx_id: int) -> Transaction | None:
        return Transaction.get_or_none(Transaction.id == tx_id)

    @staticmethod
    def query(
        wallet: Wallet | str | int | None = None,
        tag: str | list[str] | None = None,
        tx_type: str | None = None,
        method: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Transaction]:
        """General multi-criterion query engine for transactions."""
        query = Transaction.select().distinct()

        if tag:
            tags = [tag] if isinstance(tag, str) else list(tag)
            clean_tags = [t.strip().lower() for t in tags]
            query = query.join(TransactionTag).join(Tag).where(Tag.name.in_(clean_tags))

        # Every other filter is just a WHERE condition
        conditions = []

        if wallet is not None:
            resolved_wallet = (
                wallet if isinstance(wallet, Wallet) else WalletService.get(wallet)
            )
            if resolved_wallet:
                conditions.append(Transaction.wallet == resolved_wallet)

        if tx_type:
            conditions.append(Transaction.tx_type == tx_type)
        if method:
            conditions.append(Transaction.method == method.lower())
        if start_date:
            conditions.append(Transaction.created_at >= start_date)
        if end_date:
            conditions.append(Transaction.created_at <= end_date)
        if search:
            keyword = f"%{search.strip()}%"
            conditions.append((Transaction.name**keyword) | (Transaction.desc**keyword))

        if conditions:
            query = query.where(*conditions)  # peewee ANDs multiple args together

        return list(
            query.order_by(Transaction.created_at.desc()).limit(limit).offset(offset)
        )

    @staticmethod
    def summary(
        wallet: Wallet | str | int | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, Decimal]:
        """Thin wrapper around Transaction.get_summary so summaries stay behind
        the service layer instead of requiring callers to reach into the model."""
        wallet_id = None
        if wallet is not None:
            resolved = (
                wallet if isinstance(wallet, Wallet) else WalletService.get(wallet)
            )
            wallet_id = resolved.id if resolved else None

        return Transaction.get_summary(
            wallet_id=wallet_id, start_date=start_date, end_date=end_date
        )

    @staticmethod
    def delete(tx_id: int) -> bool:
        """Deletes a transaction and updates the wallet balance."""
        with db.atomic():
            tx = TransactionService.get(tx_id)
            if not tx:
                return False

            wallet = tx.wallet
            tx.delete_instance()
            wallet.sync_balance()
            return True
