#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ЧАТ-АГЕНТ №1 - Координатор
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Agent1:
    def __init__(self):
        logger.info("🚀 Агент №1 инициализирован")
    
    def run(self):
        logger.info("✅ Агент №1 запущен и слушает очередь")
        asyncio.run(self.listen())
    
    async def listen(self):
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("❌ Агент №1 остановлен")

if __name__ == "__main__":
    agent = Agent1()
    agent.run()
