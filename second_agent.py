import requests
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, Text, Boolean, ForeignKey, TIMESTAMP, func
from sqlalchemy.orm import declarative_base, sessionmaker

# --- НАСТРОЙКА ---
DB_URL = "postgresql+psycopg2://user:password@localhost:5432/dbname"  # укажи свои данные подключения к Postgres!
AUTH_KEY = "YOUR_GIGACHAT_AUTH_KEY"

# --- SQLAlchemy ORM ---
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    sender_username = Column(String)
    sender_id = Column(BigInteger)
    message_text = Column(Text)
    message_link = Column(String)
    created_at = Column(TIMESTAMP, server_default=func.now())

class NegativeMessage(Base):
    __tablename__ = "negative_messages"
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    message_link = Column(String)
    sender_username = Column(String)
    negative_reason = Column(Text)
    is_sent_to_moderators = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

# --- GIGACHAT ---
def get_gigachat_token(auth_key):
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    headers = {"Authorization": f"Basic {auth_key}"}
    response = requests.post(url, headers=headers)
    token = response.json().get("access_token", "")
    return token

def check_message_with_gigachat(message, rules, prompt, token):
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    rules_text = "\n".join(rules)
    system_msg = f"Правила чата:\n{rules_text}\n\n{prompt}"
    user_msg = f"Сообщение:\n{message}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = {
        "model": "GigaChat",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ],
        "temperature": 0.2,
        "max_tokens": 256
    }
    response = requests.post(url, headers=headers, json=data)
    result = response.json()
    try:
        content = result["choices"][0]["message"]["content"]
    except Exception as e:
        content = f"Ошибка: {result}, {e}"
    return content

def parse_gigachat_response(text):
    ban = any(word in text.lower() for word in ["бан", "ban", "block"])
    return ban, text

# --- ОСНОВНАЯ ЛОГИКА ---
def agent_main(chat_id, rules):
    session = SessionLocal()
    token = get_gigachat_token(AUTH_KEY)
    prompt = "Проанализируй сообщение на нарушения правил чата. Ответь строго в формате: 'Вердикт: да/нет. Причина: ...'"

    messages = session.query(Message).filter_by(chat_id=chat_id).order_by(Message.created_at.desc()).limit(100).all()
    for msg in messages:
        ban, reason = parse_gigachat_response(
            check_message_with_gigachat(msg.message_text, rules, prompt, token)
        )
        if ban:
            # Проверяем, нет ли уже такого негативного сообщения
            exists = session.query(NegativeMessage).filter_by(message_link=msg.message_link).first()
            if not exists:
                neg_msg = NegativeMessage(
                    chat_id=msg.chat_id,
                    message_link=msg.message_link,
                    sender_username=msg.sender_username,
                    negative_reason=reason
                )
                session.add(neg_msg)
                print(f"Нарушение добавлено: {msg.message_link} — {reason}")
            else:
                print(f"Уже есть негативное сообщение: {msg.message_link}")
    session.commit()
    session.close()

# --- ПРИМЕР ЗАПУСКА ---
if __name__ == "__main__":
    rules = [
        "Запрещена реклама сторонних сообществ",
        "Запрещён флуд и спам",
        "Запрещены оскорбления участников"
    ]
    chat_id = 1  # номер чата из БД (можно сделать параметром)
    agent_main(chat_id, rules)
