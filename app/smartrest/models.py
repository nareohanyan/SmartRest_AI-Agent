from __future__ import annotations

from functools import lru_cache

import sqlalchemy as sa
from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker
from sqlalchemy.schema import MetaData

from app.db.operational import get_operational_engine, get_operational_session_factory
from app.schemas.subscription import AIAgentSubscriptionStatus

naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=naming_convention)
Base = declarative_base(metadata=metadata)


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP"))


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint(
            "ai_agent_subscription_status IN "
            "('active', 'trial', 'expired', 'cancelled', 'suspended')",
            name="ai_agent_subscription_status",
        ),
    )
    id = Column(BigInteger, primary_key=True)
    name = Column(String(255), nullable=True)
    profile_nick = Column(String(255), nullable=True)
    billing_status = Column(SmallInteger, nullable=True)
    billing_start_time = Column(DateTime(timezone=True), nullable=True)
    billing_end_time = Column(DateTime(timezone=True), nullable=True)
    currency = Column(SmallInteger, nullable=True)
    ai_agent_subscription_status = Column(
        String(32),
        nullable=False,
        server_default=sa.text(f"'{AIAgentSubscriptionStatus.EXPIRED.value}'"),
    )
    ai_agent_subscription_expires_at = Column(DateTime(timezone=True), nullable=True)

    users = relationship("User", back_populates="profile", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="profile", cascade="all, delete-orphan")
    clients = relationship("Client", back_populates="profile", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Profile id={self.id} name={self.name!r}>"


class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    username = Column(String(255), nullable=False, unique=True)
    status = Column(String(16), nullable=True)
    reports = Column(Integer, nullable=True)
    role_id = Column(BigInteger, nullable=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))

    profile = relationship("Profile", back_populates="users")


class Hall(Base):
    __tablename__ = "halls"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    name = Column(String(255), nullable=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)
    floor_id = Column(BigInteger, nullable=True)


class Staff(Base):
    __tablename__ = "staff"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    firstname = Column(String(255), nullable=True)
    lastname = Column(String(255), nullable=True)
    position = Column(String(255), nullable=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    salary_value = Column(String(255), nullable=True)
    dismission_date = Column(DateTime(timezone=True), nullable=True)


class BreakPoint(Base):
    __tablename__ = "break_points"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    date = Column(DateTime(timezone=True), nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)


class Log(Base):
    __tablename__ = "logs"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id"), index=True, nullable=True)
    category = Column(String(255), nullable=True)
    action = Column(Text, nullable=True)
    date = Column(DateTime(timezone=True), nullable=True, index=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))


class Table(Base):
    __tablename__ = "tables"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    room_table_name = Column(String(255), nullable=True)
    hall_id = Column(BigInteger, ForeignKey("halls.id"), index=True, nullable=True)
    delivery = Column(Boolean, nullable=True, server_default=sa.text("false"))
    service_commissions_type = Column(String(64), nullable=True)
    service_commissions_value = Column(Text, nullable=True)
    max_people = Column(Integer, nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    hotel_room_status = Column(String(64), nullable=True)

    orders = relationship("Order", back_populates="table")


class Order(Base):
    __tablename__ = "orders"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    profile_order_uniq_id = Column(String(64), nullable=True, unique=True)
    room_table_id = Column(BigInteger, ForeignKey("tables.id"), index=True, nullable=True)
    profile_staff_id = Column(BigInteger, ForeignKey("staff.id"), index=True, nullable=True)
    room_table_status = Column(String(64), nullable=True)
    order_create_date = Column(DateTime(timezone=True), index=True, nullable=True)
    delivery_id = Column(BigInteger, nullable=True)
    delivery_date = Column(DateTime(timezone=True), nullable=True)
    client_id = Column(BigInteger, ForeignKey("clients.id"), index=True, nullable=True)
    table_commissions_type = Column(String(64), nullable=True)
    table_commissions_value = Column(Text, nullable=True)
    total_price = Column(Numeric(18, 4), nullable=True)
    sale = Column(Numeric(18, 4), nullable=True)
    payed = Column(Integer, nullable=True, server_default=sa.text("0"))
    payment_status = Column(String(64), nullable=True)
    json = Column("json", JSONB, nullable=True)
    tip = Column(Integer, nullable=True)
    deposit = Column(Integer, nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)
    final_total = Column(Numeric(18, 4), nullable=True)
    time_percent = Column(Numeric(10, 4), nullable=True)
    fix_percent = Column(Numeric(10, 4), nullable=True)
    clients_count = Column(Integer, nullable=True)
    status_id = Column(SmallInteger, nullable=True)
    terminate_date = Column(DateTime(timezone=True), nullable=True)
    type_id = Column(SmallInteger, nullable=True)
    delivery_price = Column(Numeric(18, 4), nullable=True)
    commission_total = Column(Numeric(18, 4), nullable=True)
    cashbox_id = Column(BigInteger, ForeignKey("cashboxes.id"), nullable=True)
    hourly_pay_without_product = Column(Boolean, nullable=True)
    is_delivery = Column(Boolean, nullable=True, server_default=sa.text("false"))
    discounted_amount = Column(Numeric(18, 4), nullable=True)
    sale_description = Column(Text, nullable=True)
    order_type = Column(SmallInteger, nullable=True)

    profile = relationship("Profile", back_populates="orders")
    table = relationship("Table", back_populates="orders")
    staff = relationship("Staff")
    client = relationship("Client")
    items = relationship("OrderContent", back_populates="order", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_orders_profile_date_paid", "profile_id", "order_create_date", "payment_status", "payed", "branch_id"),
    )


class OrderContent(Base):
    __tablename__ = "order_contents"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    room_table_order_id = Column(BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False)
    subtable_id = Column(BigInteger, nullable=True)
    suborder_id = Column(BigInteger, nullable=True)
    profile_menu_item_id = Column(BigInteger, ForeignKey("menu_items.id"), index=True, nullable=True)
    profile_menu_item_count = Column(Numeric(18, 6), nullable=True)
    cost_price = Column(Numeric(18, 4), nullable=True)
    item_price = Column(Numeric(18, 4), nullable=True)
    create_date = Column(DateTime(timezone=True), index=True, nullable=True)
    json = Column("json", JSONB, nullable=True)
    cashback_value = Column(Numeric(18, 4), nullable=True)
    done = Column(Boolean, nullable=True, server_default=sa.text("false"))
    product_sale = Column(Numeric(18, 4), nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)
    staff_id = Column(BigInteger, ForeignKey("staff.id"), index=True, nullable=True)
    order_in = Column(SmallInteger, nullable=True)
    e_marks = Column(JSONB, nullable=True)

    order = relationship("Order", back_populates="items")
    menu_item = relationship("MenuItem")

    __table_args__ = (
        Index("ix_order_contents_order", "room_table_order_id"),
        Index("ix_order_contents_menu_item", "profile_menu_item_id"),
    )


class OrderContentRemoved(Base):
    __tablename__ = "order_content_removed"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    room_table_order_id = Column(BigInteger, ForeignKey("orders.id"), index=True, nullable=True)
    suborder_id = Column(BigInteger, nullable=True)
    profile_menu_item_id = Column(BigInteger, ForeignKey("menu_items.id"), index=True, nullable=True)
    profile_menu_item_count = Column(Numeric(18, 6), nullable=True)
    create_date = Column(DateTime(timezone=True), nullable=True)
    remove_date = Column(DateTime(timezone=True), nullable=True)
    json = Column("json", JSONB, nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)
    add_date = Column(DateTime(timezone=True), nullable=True)


class OrderPackageComponent(Base):
    __tablename__ = "profiles_room_table_order_package_components"
    id = Column(BigInteger, primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP"))
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    room_table_order_content_id = Column(BigInteger, ForeignKey("order_contents.id", ondelete="CASCADE"), index=True, nullable=False)
    profile_menu_item_id = Column(BigInteger, ForeignKey("menu_items.id"), index=True, nullable=True)
    profile_menu_item_count = Column(Numeric(18, 6), nullable=True)
    cost_price = Column(Numeric(18, 4), nullable=True)
    item_price = Column(Numeric(18, 4), nullable=True)
    json = Column("json", JSONB, nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)

class Cashbox(Base):
    __tablename__ = "cashboxes"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    cash_value = Column(Numeric(18, 4), nullable=True)
    currency = Column(String(16), nullable=False)
    modify_date = Column(DateTime(timezone=True), nullable=True)
    set_default = Column(String(16), nullable=True, server_default=sa.text("'false'"))
    cashbox_name = Column(String(256), nullable=True)
    cashbox_name_ru = Column(String(256), nullable=True)
    cashbox_name_en = Column(String(256), nullable=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    is_bank = Column(Boolean, nullable=True, server_default=sa.text("false"))
    branch_id = Column(BigInteger, ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    is_card = Column(Boolean, nullable=True, server_default=sa.text("false"))
    print_fiscal = Column(Integer, nullable=True, server_default=sa.text("0"))


class Client(Base):
    __tablename__ = "clients"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    name = Column(String(255), nullable=True)
    address = Column(Text, nullable=True)
    phone = Column(String(64), nullable=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    email = Column(String(255), nullable=True)
    sex = Column(Integer, nullable=True)
    company = Column(BigInteger, nullable=True)
    remote_id = Column(String(64), nullable=True)
    identification_document = Column(String(64), nullable=True)

    profile = relationship("Profile", back_populates="clients")
    cards_history = relationship("ClientCardHistory", back_populates="client")


class ClientCard(Base):
    __tablename__ = "client_cards"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    client_id = Column(BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), index=True, nullable=False)
    card_number = Column(String(255), nullable=True)
    type = Column(Boolean, nullable=True)
    percent = Column(String(16), nullable=True)
    balance = Column(SmallInteger, nullable=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    created = Column(DateTime(timezone=True), nullable=True)
    remote_id = Column(BigInteger, nullable=True)


class ClientCardHistory(Base):
    __tablename__ = "clients_cards_history"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    client_id = Column(BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), index=True, nullable=False)
    card_code = Column(String(64), nullable=True)
    value = Column(Numeric(18, 4), nullable=True)
    balance = Column(Numeric(18, 4), nullable=True)
    create_date = Column(DateTime(timezone=True), nullable=True, index=True)
    menu_item_id = Column(BigInteger, ForeignKey("menu_items.id"), index=True, nullable=True)
    menu_item_count = Column(Numeric(18, 6), nullable=True)
    menu_item_balance = Column(Numeric(18, 6), nullable=True)
    menu_item_price = Column(Numeric(18, 4), nullable=True)
    room_table_order_id = Column(BigInteger, ForeignKey("orders.id"), index=True, nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)
    bonus_id = Column(BigInteger, nullable=True)
    bonus_name = Column(String(255), nullable=True)

    client = relationship("Client", back_populates="cards_history")


class BalanceHistory(Base, TimestampMixin):
    __tablename__ = "balance_history"
    id = Column(BigInteger, primary_key=True)
    original_create_date = Column(DateTime(timezone=True), nullable=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    store_id = Column(BigInteger, ForeignKey("stores.id"), nullable=True)
    material_id = Column(BigInteger, ForeignKey("materials.id"), index=True, nullable=True)
    document_id = Column(BigInteger, ForeignKey("documents.id"), index=True, nullable=True)
    type_id = Column(SmallInteger, nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)
    quantity_in = Column(Numeric(18, 6), nullable=True)
    quantity_out = Column(Numeric(18, 6), nullable=True)
    balance = Column(Numeric(18, 6), nullable=True)
    order_id = Column(BigInteger, ForeignKey("orders.id"), index=True, nullable=True)
    order_content_id = Column(BigInteger, ForeignKey("order_contents.id"), index=True, nullable=True)
    price = Column(Numeric(18, 6), nullable=True)
    document_content_id = Column(BigInteger, ForeignKey("document_contents.id"), index=True, nullable=True)
    useful_weight_quantity = Column(Numeric(18, 6), nullable=True)
    fix_price = Column(Numeric(18, 6), nullable=True)
    fix_balance = Column(Numeric(18, 6), nullable=True)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    company_id = Column(BigInteger, nullable=True)
    type_id = Column(BigInteger, ForeignKey("document_types.id"), index=True, nullable=True)
    status_id = Column(SmallInteger, nullable=True)
    order_id = Column(BigInteger, ForeignKey("orders.id"), index=True, nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)
    back_date = Column(DateTime(timezone=True), nullable=True)
    identification_number = Column(String(64), nullable=True)

    contents = relationship("DocumentContent", back_populates="document", cascade="all, delete-orphan")


class DocumentContent(Base, TimestampMixin):
    __tablename__ = "document_contents"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    document_id = Column(BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    store_id = Column(BigInteger, ForeignKey("stores.id"), nullable=True)
    material_content_id = Column(BigInteger, ForeignKey("material_content.id"), index=True, nullable=True)
    quantity_in = Column(Numeric(18, 6), nullable=True)
    quantity_out = Column(Numeric(18, 6), nullable=True)
    price = Column(Numeric(18, 6), nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)
    referer_id = Column(BigInteger, nullable=True)
    fifo_state_id = Column(BigInteger, ForeignKey("fifo_state.id"), index=True, nullable=True)
    useful_weight_quantity = Column(Numeric(18, 6), nullable=True)
    st_balance_create_status = Column(Boolean, nullable=True)

    document = relationship("Document", back_populates="contents")


class DocumentType(Base, TimestampMixin):
    __tablename__ = "document_types"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    automatic = Column(Boolean, nullable=True)
    order_in = Column(Boolean, nullable=True)


class DocumentTypeTemplate(Base, TimestampMixin):
    __tablename__ = "document_type_template"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    document_type_id = Column(BigInteger, ForeignKey("document_types.id"), index=True, nullable=False)
    name = Column(String(255), nullable=True)


class Material(Base, TimestampMixin):
    __tablename__ = "materials"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    material_category_id = Column(BigInteger, ForeignKey("material_category.id"), index=True, nullable=True)
    semi_finished = Column(Boolean, nullable=True, server_default=sa.text("false"))
    useful_weight = Column(Boolean, nullable=True)


class MaterialContent(Base, TimestampMixin):
    __tablename__ = "material_content"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    material_id = Column(BigInteger, ForeignKey("materials.id"), index=True, nullable=True)
    unit_id = Column(BigInteger, ForeignKey("units.id"), index=True, nullable=True)
    price = Column(Numeric(18, 6), nullable=True)
    min_quantity = Column(Numeric(18, 6), nullable=True)
    code = Column(String(64), nullable=True)
    product_balance = Column(Numeric(18, 6), nullable=True)
    pre_pack_mass = Column(Numeric(18, 6), nullable=True)


class MaterialCategory(Base, TimestampMixin):
    __tablename__ = "material_category"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)


class MaterialCategoryLanguage(Base, TimestampMixin):
    __tablename__ = "material_category_language"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    language_id = Column(BigInteger, nullable=True)
    title = Column(String(255), nullable=True)
    material_category_id = Column(BigInteger, ForeignKey("material_category.id"), index=True, nullable=True)


class MaterialLanguage(Base, TimestampMixin):
    __tablename__ = "material_language"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    language_id = Column(BigInteger, nullable=True)
    title = Column(String(255), nullable=True)
    material_id = Column(BigInteger, ForeignKey("materials.id"), index=True, nullable=True)

class Store(Base):
    __tablename__ = "stores"
    id = Column(BigInteger, primary_key=True)
    modifier = Column(String(255), nullable=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id", ondelete="CASCADE"), index=True)

class StoreLanguage(Base, TimestampMixin):
    __tablename__ = "store_language"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    language_id = Column(BigInteger, nullable=True)
    title = Column(String(255), nullable=True)
    store_id = Column(BigInteger, ForeignKey("stores.id"), nullable=True)


class Measurement(Base, TimestampMixin):
    __tablename__ = "units"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)


class MeasurementLanguage(Base, TimestampMixin):
    __tablename__ = "unit_language"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    language_id = Column(BigInteger, nullable=True)
    title = Column(String(255), nullable=True)
    unit_id = Column(BigInteger, ForeignKey("units.id"), index=True, nullable=True)


class FIFOHistory(Base, TimestampMixin):
    __tablename__ = "fifo_history"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    state_id = Column(BigInteger, ForeignKey("fifo_state.id"), index=True, nullable=True)
    quantity_in = Column(Numeric(18, 6), nullable=True)
    quantity_out = Column(Numeric(18, 6), nullable=True)
    document_id = Column(BigInteger, ForeignKey("documents.id"), index=True, nullable=True)
    document_content_id = Column(BigInteger, ForeignKey("document_contents.id"), index=True, nullable=True)
    order_id = Column(BigInteger, ForeignKey("orders.id"), index=True, nullable=True)
    order_content_id = Column(BigInteger, ForeignKey("order_contents.id"), index=True, nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)
    changed = Column(Boolean, nullable=True, server_default=sa.text("false"))


class FIFOState(Base, TimestampMixin):
    __tablename__ = "fifo_state"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    store_id = Column(BigInteger, ForeignKey("stores.id"), nullable=True)
    item_id = Column(BigInteger, ForeignKey("material_content.id"), nullable=True)
    price = Column(Numeric(18, 6), nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)


class FiscalReceipt(Base, TimestampMixin):
    __tablename__ = "fiscal_receipt"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    order_id = Column(BigInteger, ForeignKey("orders.id"), index=True, nullable=True)
    report_type = Column(BigInteger, nullable=True)
    report_start = Column(BigInteger, nullable=True)
    report_end = Column(BigInteger, nullable=True)
    status = Column(BigInteger, nullable=True)
    order_prepayment = Column(Boolean, nullable=True)
    order_history_id = Column(BigInteger, nullable=True)
    return_receipt_id = Column(BigInteger, nullable=True)


class FiscalReceiptHistory(Base, TimestampMixin):
    __tablename__ = "fiscal_receipt_history"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    receipt_id = Column(BigInteger, ForeignKey("fiscal_receipt.id"), index=True, nullable=True)
    rseq = Column("rseq", BigInteger, nullable=True)
    crn = Column("crn", String(64), nullable=True)
    sn = Column("sn", String(64), nullable=True)
    tin = Column(String(64), nullable=True)
    time = Column(DateTime(timezone=True), nullable=True)
    fiscal = Column(String(64), nullable=True)
    total = Column(Numeric(18, 4), nullable=True)
    change = Column(Numeric(18, 4), nullable=True)


class Branch(Base, TimestampMixin):
    __tablename__ = "branches"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)


class MenuItem(Base):
    __tablename__ = "menu_items"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column("profile", BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False, key="profile_id")
    group_id = Column("group", BigInteger, ForeignKey("menu_group.id"), index=True, nullable=True, key="group_id")
    name = Column(String(255), nullable=True)
    name_ru = Column(String(255), nullable=True)
    name_en = Column(String(255), nullable=True)
    price = Column(Numeric(18, 4), nullable=True)
    check_place = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    barcode = Column(String(128), nullable=True)
    frozen = Column(Boolean, nullable=True, server_default=sa.text("false"))
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    type = Column(SmallInteger, nullable=True)
    suspended = Column(Boolean, nullable=True, server_default=sa.text("false"))
    suspend_date = Column(DateTime(timezone=True), nullable=True)
    activate_date = Column(DateTime(timezone=True), nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)
    hdm_name = Column(String(255), nullable=True)
    code = Column(String(64), nullable=True)


class MenuGroup(Base):
    __tablename__ = "menu_group"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column("profile", BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False, key="profile_id")
    place_id = Column("place", BigInteger, ForeignKey("menu_place.id"), index=True, nullable=True, key="place_id")
    title = Column(String(255), nullable=True)
    title_ru = Column(String(255), nullable=True)
    title_en = Column(String(255), nullable=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)


class MenuPlace(Base):
    __tablename__ = "menu_place"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column("profile", BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False, key="profile_id")
    title = Column(String(255), nullable=True)
    title_ru = Column(String(255), nullable=True)
    title_en = Column(String(255), nullable=True)
    store_id = Column(BigInteger, ForeignKey("stores.id"), nullable=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)


class MovedItem(Base, TimestampMixin):
    __tablename__ = "moved_items"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    order_id = Column(BigInteger, ForeignKey("orders.id"), index=True, nullable=True)
    new_order_id = Column(BigInteger, ForeignKey("orders.id"), index=True, nullable=True)
    order_uniq_id = Column(String(64), nullable=True)
    new_order_uniq_id = Column(String(64), nullable=True)
    content_id = Column(BigInteger, ForeignKey("order_contents.id"), index=True, nullable=True)
    menu_item_id = Column(BigInteger, ForeignKey("menu_items.id"), index=True, nullable=True)
    menu_item_count = Column(Numeric(18, 6), nullable=True)
    table_id = Column(BigInteger, ForeignKey("tables.id"), index=True, nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)


class MenuItemContent(Base):
    __tablename__ = "menu_item_content"
    id = Column(BigInteger, primary_key=True)
    profile_id = Column("profile", BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False, key="profile_id")
    menu_item_id = Column("menu_item", BigInteger, ForeignKey("menu_items.id"), index=True, nullable=True, key="menu_item_id")
    store_item_id = Column("store_item", BigInteger, ForeignKey("material_content.id"), index=True, nullable=True, key="store_item_id")
    store_item_count = Column(BigInteger, nullable=True)
    package_id = Column(BigInteger, nullable=True)
    visibility = Column(Boolean, nullable=True)
    store_id = Column(BigInteger, ForeignKey("stores.id"), nullable=True)
    suspended = Column(Boolean, nullable=True, server_default=sa.text("false"))
    branch_id = Column(BigInteger, ForeignKey("branches.id"), index=True, nullable=True)


class OrderPaymentHistory(Base, TimestampMixin):
    __tablename__ = "order_payment_history"
    id = Column(BigInteger, primary_key=True)
    deleted = Column(Boolean, nullable=True, server_default=sa.text("false"))
    archived = Column(Boolean, nullable=True, server_default=sa.text("false"))
    profile_id = Column(BigInteger, ForeignKey("profiles.id", ondelete="CASCADE"), index=True, nullable=False)
    order_id = Column(BigInteger, ForeignKey("orders.id"), index=True, nullable=True)
    total_price = Column(Numeric(18, 4), nullable=True)
    payed = Column(Numeric(18, 4), nullable=True, server_default=sa.text("0"))
    cashbox_id = Column(BigInteger, ForeignKey("cashboxes.id"), nullable=True)
    card_id = Column(BigInteger, ForeignKey("client_cards.id"), nullable=True)
    cashbox_history_id = Column(BigInteger, nullable=True)


class Translate(Base):
    __tablename__ = "translate"
    id = Column("Id", BigInteger, primary_key=True)
    string = Column(String(255), nullable=False, unique=True, index=True)
    en = Column(Text, nullable=True)
    hy = Column(Text, nullable=True)
    ru = Column(Text, nullable=True)

class MigrationTableMap(Base):
    __tablename__ = "table_map"
    __table_args__ = {"schema": "migrations"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    src_table = Column(String(255), nullable=False)
    dst_table = Column(String(255), nullable=False)
    src_pk = Column(String(255), nullable=True)
    comment = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=sa.text("true"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    columns = relationship("MigrationColumnMap", back_populates="table_map", cascade="all, delete-orphan")


class MigrationColumnMap(Base):
    __tablename__ = "column_map"
    __table_args__ = {"schema": "migrations"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    table_map_id = Column(BigInteger, ForeignKey("migrations.table_map.id", ondelete="CASCADE"), nullable=False, index=True)
    src_column = Column(String(255), nullable=False)
    dst_column = Column(String(255), nullable=False)
    transform = Column(Text, nullable=True)

    table_map = relationship("MigrationTableMap", back_populates="columns")


class SourceSystem(Base):
    __tablename__ = "source_systems"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'readonly', 'disabled')",
            name="status",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    server_name = Column(String(255), nullable=False)
    cloud_num = Column(Integer, nullable=False)
    status = Column(
        String(32),
        nullable=False,
        server_default=sa.text("'active'"),
    )
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    canonical_profiles = relationship("CanonicalProfile", back_populates="source_system")
    profile_source_maps = relationship("ProfileSourceMap", back_populates="source_system", cascade="all, delete-orphan")
    canonical_source_maps = relationship("CanonicalSourceMap", back_populates="source_system", cascade="all, delete-orphan")


class CanonicalProfile(Base):
    __tablename__ = "canonical_profiles"
    __table_args__ = (
        CheckConstraint(
            "status IN "
            "('active', 'suspended', 'deleted')",
            name="status",
        ),
        UniqueConstraint("profile_nick", name="uq_canonical_profiles_profile_nick"),
        UniqueConstraint(
            "source_system_id",
            "profile_id",
            name="uq_canonical_profiles_source_system_profile_id",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_system_id = Column(
        BigInteger,
        ForeignKey("source_systems.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    profile_id = Column(BigInteger, nullable=False)
    profile_nick = Column(String(255), nullable=False)
    status = Column(
        String(32),
        nullable=False,
        server_default=sa.text("'active'"),
    )
    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    source_system = relationship("SourceSystem", back_populates="canonical_profiles")
    canonical_users = relationship("CanonicalUser", back_populates="canonical_profile", cascade="all, delete-orphan")
    profile_source_maps = relationship("ProfileSourceMap", back_populates="canonical_profile", cascade="all, delete-orphan")


class CanonicalUser(Base):
    __tablename__ = "canonical_users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'suspended', 'deleted')",
            name="status",
        ),
        UniqueConstraint(
            "canonical_profile_id",
            "user_id",
            name="uq_canonical_users_profile_user_id",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    canonical_profile_id = Column(
        BigInteger,
        ForeignKey("canonical_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id = Column(BigInteger, nullable=False)
    username = Column(String(255), nullable=True)
    status = Column(
        String(32),
        nullable=False,
        server_default=sa.text("'active'"),
    )
    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    canonical_profile = relationship("CanonicalProfile", back_populates="canonical_users")
    canonical_source_maps = relationship("CanonicalSourceMap", back_populates="canonical_user", cascade="all, delete-orphan")


class ProfileSourceMap(Base):
    __tablename__ = "profile_source_maps"
    __table_args__ = (
        UniqueConstraint(
            "source_system_id",
            "profile_id",
            name="uq_profile_source_maps_source_system_profile_id",
        ),
        UniqueConstraint(
            "canonical_profile_id",
            "source_system_id",
            name="uq_profile_source_maps_canonical_profile_source_system",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_system_id = Column(
        BigInteger,
        ForeignKey("source_systems.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    canonical_profile_id = Column(
        BigInteger,
        ForeignKey("canonical_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    profile_id = Column(BigInteger, nullable=False)
    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    source_system = relationship("SourceSystem", back_populates="profile_source_maps")
    canonical_profile = relationship("CanonicalProfile", back_populates="profile_source_maps")


class CanonicalSourceMap(Base):
    __tablename__ = "canonical_source_maps"
    __table_args__ = (
        UniqueConstraint(
            "source_system_id",
            "profile_id",
            "user_id",
            name="uq_canonical_source_maps_source_profile_user",
        ),
        UniqueConstraint(
            "canonical_user_id",
            "source_system_id",
            name="uq_canonical_source_maps_canonical_user_source",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_system_id = Column(
        BigInteger,
        ForeignKey("source_systems.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    canonical_user_id = Column(
        BigInteger,
        ForeignKey("canonical_users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    profile_id = Column(BigInteger, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    source_system = relationship("SourceSystem", back_populates="canonical_source_maps")
    canonical_user = relationship("CanonicalUser", back_populates="canonical_source_maps")


class SyncState(Base):
    __tablename__ = "sync_state"
    __table_args__ = (
        UniqueConstraint(
            "source_system_id",
            "stream_name",
            name="uq_sync_state_source_stream",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_system_id = Column(
        BigInteger,
        ForeignKey("source_systems.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    stream_name = Column(String(128), nullable=False)
    last_cursor = Column(BigInteger, nullable=True)
    last_synced_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    source_system = relationship("SourceSystem")


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'partial', 'failed')",
            name="status",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_system_id = Column(
        BigInteger,
        ForeignKey("source_systems.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status = Column(
        String(32),
        nullable=False,
        server_default=sa.text("'running'"),
    )
    started_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True)
    profiles_processed = Column(Integer, nullable=False, server_default=sa.text("0"))
    users_processed = Column(Integer, nullable=False, server_default=sa.text("0"))
    errors_count = Column(Integer, nullable=False, server_default=sa.text("0"))
    details = Column(JSONB, nullable=True)

    source_system = relationship("SourceSystem")
    errors = relationship("SyncError", back_populates="sync_run", cascade="all, delete-orphan")


class SyncError(Base):
    __tablename__ = "sync_errors"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sync_run_id = Column(
        BigInteger,
        ForeignKey("sync_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_system_id = Column(
        BigInteger,
        ForeignKey("source_systems.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    stream_name = Column(String(128), nullable=False)
    entity_key = Column(String(255), nullable=True)
    error_code = Column(String(64), nullable=False)
    error_message = Column(Text, nullable=False)
    payload_fragment = Column(JSONB, nullable=True)
    occurred_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    sync_run = relationship("SyncRun", back_populates="errors")
    source_system = relationship("SourceSystem")


def get_sync_engine() -> Engine:
    return get_operational_engine()


@lru_cache(maxsize=1)
def get_sync_session_factory() -> sessionmaker[Session]:
    return get_operational_session_factory()


class _SyncSessionLocalProxy:
    def __call__(self, *args: object, **kwargs: object) -> Session:
        return get_sync_session_factory()(*args, **kwargs)

    def __getattr__(self, name: str) -> object:
        return getattr(get_sync_session_factory(), name)


SyncSessionLocal = _SyncSessionLocalProxy()


__all__ = [
    "Base",
    # Core
    "Profile", "User", "Hall", "Staff", "BreakPoint", "Log", "Table",
    "Order", "OrderContent", "OrderContentRemoved", "OrderPackageComponent",
    "Client", "ClientCardHistory",
    # Inventory / docs
    "BalanceHistory", "Document", "DocumentContent", "DocumentType", "DocumentTypeTemplate",
    "Material", "MaterialContent", "MaterialCategory", "MaterialCategoryLanguage", "MaterialLanguage",
    "StoreLanguage", "Measurement", "MeasurementLanguage",
    # FIFO & fiscal
    "FIFOHistory", "FIFOState",
    "FiscalReceipt", "FiscalReceiptHistory",
    # Org & menu
    "Branch", "MenuItem", "MenuGroup", "MenuPlace", "MovedItem",
    "MenuItemContent", "OrderPaymentHistory", "Translate",
    # Migration helpers
    "MigrationTableMap", "MigrationColumnMap",
    # Canonical identity helpers
    "SourceSystem", "CanonicalProfile", "CanonicalUser", "ProfileSourceMap", "CanonicalSourceMap",
    "SyncState", "SyncRun", "SyncError",
    # Engine/session helpers
    "get_sync_engine", "get_sync_session_factory", "SyncSessionLocal"
]
