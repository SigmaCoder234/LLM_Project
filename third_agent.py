#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ЧАТ-АГЕНТ №3 - GigaChat модератор
"""

import asyncio
import logging
import redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_HOST = "localhost"
REDIS_PORT = 6379

class Agent3:
    def __init__(self):
        try:
            self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            self.redis_client.ping()
            logger.info("🚀 Агент №3 инициализирован")
        except Exception as e:
            logger.error(f"❌ Ошибка Redis: {e}")
            self.redis_client = None
    
    def run(self):
        logger.info("✅ Агент №3 запущен и слушает очередь")
        asyncio.run(self.listen())
    
    async def listen(self):
        try:
            while True:
                if self.redis_client:
                    try:
                        msg = self.redis_client.blpop("queue:agent3_input", timeout=1)
                        if msg:
                            logger.info(f"📨 Сообщение получено: {msg}")
                    except:
                        pass
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("❌ Агент №3 остановлен")

if __name__ == "__main__":
    agent = Agent3()
    agent.run()
