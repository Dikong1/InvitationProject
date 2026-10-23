import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Boolean, Text, ForeignKey, DateTime, func, Enum as SAEnum, Index, text
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class QuestionType(str, enum.Enum):
    boolean = "boolean"  # Вопрос с ответом «Да» или «Нет»
    number = "number"    # Вопрос с числовым ответом (например, количество гостей)
    text = "text"        # Вопрос со свободным текстовым ответом
    select = "select"    # Вопрос с выбором из предложенных вариантов


class RSVPQuestion(Base):
    __tablename__ = "rsvp_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )  # Уникальный идентификатор вопроса (UUID)
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invitations.id", ondelete="CASCADE"),
        nullable=False, index=True
    )  # Приглашение, к которому относится данный вопрос
    question_text_kk: Mapped[str] = mapped_column(Text, nullable=False)  # Текст вопроса на казахском языке
    question_text_ru: Mapped[str] = mapped_column(Text, nullable=False)  # Текст вопроса на русском языке
    question_type: Mapped[QuestionType] = mapped_column(
        SAEnum(QuestionType, name="questiontype"), default=QuestionType.text, nullable=False
    )  # Тип вопроса: boolean / number / text / select
    options: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)  # Варианты ответов для типа select (JSON-массив строк)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # Обязателен ли ответ на этот вопрос для отправки формы
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # Порядок отображения вопроса в форме RSVP

    def __repr__(self) -> str:
        return f"<RSVPQuestion id={self.id}>"


class Invitee(Base):
    """A guest the host invited by name; their personal link carries `token`."""
    __tablename__ = "rsvp_invitees"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )  # Уникальный идентификатор приглашённого гостя (UUID)
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invitations.id", ondelete="CASCADE"),
        nullable=False, index=True
    )  # Приглашение, в список гостей которого входит этот гость
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # Имя гостя, как его записал организатор (для приветствия)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # Телефон гостя (необязательно)
    token: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)  # Токен персональной ссылки (?g=...); хранится открыто, чтобы организатор мог снова скопировать ссылку
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )  # Дата и время добавления гостя

    def __repr__(self) -> str:
        return f"<Invitee id={self.id} name={self.name}>"


class RSVPResponse(Base):
    __tablename__ = "rsvp_responses"
    __table_args__ = (
        # One response per invited guest; responses without a personal link are unaffected
        Index(
            "uq_rsvp_responses_invitee_id", "invitee_id",
            unique=True, postgresql_where=text("invitee_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )  # Уникальный идентификатор ответа (UUID)
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invitations.id", ondelete="CASCADE"),
        nullable=False, index=True
    )  # Приглашение, на которое оставлен данный ответ
    guest_name: Mapped[str] = mapped_column(String(255), nullable=False)  # Имя гостя, заполнившего форму
    guest_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)  # Телефон гостя (используется для дедупликации: один телефон — один ответ)
    will_attend: Mapped[bool] = mapped_column(Boolean, nullable=False)  # Подтверждает ли гость своё присутствие на мероприятии
    guest_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # Количество человек, которых гость приведёт с собой
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Пожелание или личный комментарий от гостя
    answers: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)  # Ответы на дополнительные RSVP-вопросы в формате {question_id: ответ}
    invitee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rsvp_invitees.id", ondelete="SET NULL"), nullable=True
    )  # Приглашённый гость, ответивший по персональной ссылке (если есть)
    wish_public: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)  # Гость разрешил показать пожелание на странице приглашения
    wish_visible: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)  # Организатор одобрил пожелание для показа (сбрасывается при изменении текста)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)  # IP-адрес гостя (используется для ограничения: не более 5 ответов с одного IP в час)
    responded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )  # Дата и время отправки ответа

    def __repr__(self) -> str:
        return f"<RSVPResponse id={self.id} guest={self.guest_name}>"
