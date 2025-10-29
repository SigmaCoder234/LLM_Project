# -*- coding: utf-8 -*-
"""
АГЕНТ №2 с PostgreSQL - Обработчик сообщений (ГОТОВЫЙ ACCESS TOKEN)
"""

import requests
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, Text, Boolean, ForeignKey, TIMESTAMP, func
from sqlalchemy.orm import declarative_base, sessionmaker

# === НАСТРОЙКИ (ГОТОВЫЙ ACCESS TOKEN) ===
DB_URL = "postgresql://tguser:mnvm7110@176.108.248.211:5432/teleguard_db?sslmode=disable"

# ГигаЧат настройки - ГОТОВЫЙ ACCESS TOKEN
GIGACHAT_ACCESS_TOKEN = "eyJjdHkiOiJqd3QiLCJlbmMiOiJBMjU2Q0JDLUhTNTEyIiwiYWxnIjoiUlNBLU9BRVAtMjU2In0.tvaS8A1YHU924PE0rt1oMkE_L336Z8K6IR2Hnli0Uo6En18sm_Z9oXC8GIL2GOoGe5kjVXNt76u1U9y4oh1OTT4MNUP__Em11DJE_wwjannYvUT3vsB8mBMSzcczwdbaaHXIihpLBuQn57OrtdEkedXCki94a5zzD4M1kH5JxV5iygd72ay3X1EEWeNKZg3rHY6iP47AIQiKwTCEfM88dhH8eAfGuyw1aFMhcd52NqHP7FtTdlN-7Bg6B9n94JBTkCeoiuicljIpujOXpD51sZXB71oJuEcbbo8ouD1zVKs6b2WNZOgApcD01UMk_B_HDbEOEMW1Wy5eAzQbawba9g.aJuKw2SQ91pqXChZVrkQ-Q.54ys0B80mnvLh0qDubBzlZmfjpPacDDzpMD0JvYKnqkHjWc27PD50fzqf9nKkNePJUxKIH4Nz5__o3c_S9fnOVKWmlzGPgMk6crHFY0SFP-xXURywdFG4wKAodJMHSnDxP_9LvwcokpL4Bmb-I2TsV9VU99QVNj9eZ1v-4_7NTYhu-Ns5836xye8fpvjHHukN4BAdR-UR5X1fXaIdHV1uKImbeI7YsSpPwRgPdWU9z7UKO2CPUJxDbultkyuVr_qenoX3fqK8ns9cbLcu2g3Q7kA-VLg1zZgCK4LaffsatQL1g8cpS_KOOif5zBIC6fbTg4SncyC5UE7Lc6paJVSvV0OkKw4xOHCZNqO6Ab_0lXwD1WbeXIxirnJs-fevhSl2mCQ2oa_UBlUjCzHDpNCibwCw12k5abxVb57LmWX30AGNzKzi796S7G6hOjDgTq242fXnThLFsAMTMGRsQqyvVCVcRIu9EWsT6sB9xq0ikfvsBlsc_bsvC9OsLtfEZsAHFC9wECJA-tuIrNYMmxhbdmKn6Ty-Bd1dd6-HfbRBFTCYOIgLg4Jt4fWThyurldOVdCl7nvm0220MndIMQ46EFVlXJNz9Wkv3TXlAl7m8_hl1IpbnnO_1lQD0uoKIBmcf2KxD2HIo0E-sV-c6REITzg9DKna4_mpRItgAkmgAjXxJgstnLJxISMzYQpe_w4QoWFM-cMuA3uxnQfpw1LMN543b_HB-I9n4mFiYRkO99E.sRM_m5RLwew6bHjt0l5QA9ImiEvKY-eLlM4CWKmav-s"

# === SQLAlchemy ORM ===
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id', ondelete='CASCADE'), nullable=False)
    sender_username = Column(String)
    sender_id = Column(BigInteger)
    message_text = Column(Text)
    message_link = Column(String)
    created_at = Column(TIMESTAMP, server_default=func.now())

class NegativeMessage(Base):
    __tablename__ = 'negative_messages'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id', ondelete='CASCADE'), nullable=False)
    message_link = Column(String)
    sender_username = Column(String)
    negative_reason = Column(Text)
    is_sent_to_moderators = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

# === GIGACHAT FUNCTIONS (ГОТОВЫЙ ACCESS TOKEN) ===
def check_message_with_gigachat(message, rules, prompt, access_token):
    """
    Проверка сообщения через GigaChat API с готовым Access Token
    
    Args:
        message: Текст сообщения для проверки
        rules: Список правил чата
        prompt: Промпт для анализа
        access_token: Access Token для GigaChat API
    
    Returns:
        str: Ответ от GigaChat или сообщение об ошибке
    """
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    
    rules_text = "\n".join(rules)
    system_msg = f"{rules_text}\n{prompt}"
    user_msg = f"{message}"
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    data = {
        'model': 'GigaChat',
        'messages': [
            {'role': 'system', 'content': system_msg},
            {'role': 'user', 'content': user_msg}
        ],
        'temperature': 0.2,
        'max_tokens': 256
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, verify=False, timeout=30)
        response.raise_for_status()
        result = response.json()
        content = result['choices'][0]['message']['content']
        return content
    except Exception as e:
        print(f"❌ Ошибка GigaChat API: {e}")
        return f"Ошибка API: {e}"

def parse_gigachat_response(text):
    """Парсинг ответа GigaChat"""
    text_lower = text.lower()
    ban = any(word in text_lower for word in ['запретить', 'блокировать', 'бан', 'нарушение'])
    return {'ban': ban, 'reason': text.strip()}

# === MAIN AGENT FUNCTION (ГОТОВЫЙ TOKEN) ===
def agent_main(chat_id, rules):
    """
    Основная функция Агента 2 для обработки сообщений
    
    Args:
        chat_id: ID чата для обработки
        rules: Список правил чата
    """
    session = SessionLocal()
    
    print("🔑 Используем готовый Access Token")
    
    prompt = "Анализируй сообщения на соответствие правилам чата. Ответь 'запретить' если нарушает правила, 'разрешить' если не нарушает."
    
    # Получаем последние 100 сообщений из чата
    messages = session.query(Message).filter_by(chat_id=chat_id).order_by(Message.created_at.desc()).limit(100).all()
    
    print(f"🔍 Агент 2: Обрабатываем {len(messages)} сообщений из чата {chat_id}")
    
    processed_count = 0
    blocked_count = 0
    
    for msg in messages:
        if not msg.message_text:
            continue
            
        print(f"📝 Проверяем сообщение: '{msg.message_text[:50]}...'")
        
        # Проверяем сообщение через GigaChat с готовым Access Token
        response_text = check_message_with_gigachat(msg.message_text, rules, prompt, GIGACHAT_ACCESS_TOKEN)
        result = parse_gigachat_response(response_text)
        
        processed_count += 1
        
        if result['ban']:
            # Проверяем, не добавляли ли уже это сообщение
            exists = session.query(NegativeMessage).filter_by(message_link=msg.message_link).first()
            if not exists:
                neg_msg = NegativeMessage(
                    chat_id=msg.chat_id,
                    message_link=msg.message_link,
                    sender_username=msg.sender_username,
                    negative_reason=result['reason']
                )
                session.add(neg_msg)
                blocked_count += 1
                print(f"🚨 Добавлено негативное сообщение: {msg.message_link} - {result['reason']}")
            else:
                print(f"⚠️ Сообщение уже обработано: {msg.message_link}")
        else:
            print(f"✅ Сообщение разрешено: {result['reason']}")
    
    session.commit()
    session.close()
    
    print(f"📊 Агент 2 завершил обработку:")
    print(f"   📝 Обработано сообщений: {processed_count}")
    print(f"   🚨 Заблокировано: {blocked_count}")
    print(f"   ✅ Разрешено: {processed_count - blocked_count}")

def test_access_token(access_token):
    """
    Тестирование Access Token
    
    Args:
        access_token: Access Token для проверки
    
    Returns:
        bool: True если токен работает
    """
    test_url = "https://gigachat.devices.sberbank.ru/api/v1/models"
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }
    
    try:
        print(f"🧪 Тестируем готовый Access Token...")
        
        response = requests.get(test_url, headers=headers, verify=False, timeout=15)
        
        if response.status_code == 200:
            models = response.json()
            print(f"✅ Access Token работает! Доступно моделей: {len(models.get('data', []))}")
            return True
        else:
            print(f"❌ Access Token не работает. Статус: {response.status_code}")
            print(f"📄 Ответ: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка тестирования токена: {e}")
        return False

# === ЗАПУСК ===
if __name__ == "__main__":
    print("=" * 60)
    print("🔧 АГЕНТ №2 - ГОТОВЫЙ ACCESS TOKEN")
    print("=" * 60)
    print("🔑 Access Token встроен в код")
    print(f"📏 Длина токена: {len(GIGACHAT_ACCESS_TOKEN)} символов")
    print("🧪 Поддерживает проверку из Telegram бота")
    print()
    
    # Проверяем токен
    if test_access_token(GIGACHAT_ACCESS_TOKEN):
        print("✅ Access Token работает отлично!")
    else:
        print("❌ Проблемы с Access Token. Проверьте токен.")
        exit(1)
    
    # Тестовые правила
    rules = [
        'Запрещена реклама', 
        'Запрещен спам', 
        'Запрещена ненормативная лексика',
        'Запрещены оскорбления'
    ]
    
    chat_id = 1  # ID чата для обработки (замените на реальный)
    
    print(f"🚀 Запускаем обработку чата {chat_id}")
    print("=" * 60)
    agent_main(chat_id, rules)