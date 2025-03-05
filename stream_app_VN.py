#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import logging
from dotenv import load_dotenv
import openai
from langdetect import detect
import asyncio  # 新增导入
import websockets  # 新增导入
import sys
from websockets.exceptions import ConnectionClosedError
from openai import OpenAI
from collections import deque  # 新增导入
from datetime import datetime, timedelta
import hashlib
from functools import lru_cache
from typing import Optional
import redis

# 导入钉钉Stream SDK
from dingtalk_stream import AckMessage
from dingtalk_stream import DingTalkStreamClient
from dingtalk_stream.chatbot import ChatbotHandler
import dingtalk_stream

# 导入配置和现有翻译类
from config import DingTalkConfig, DeepSeekConfig

# 导入 ChatbotMessage 类
from chatbot import ChatbotMessage

# 新增配置项（可添加到config.py）
RATE_LIMIT = 10  # 每分钟最大请求数
CACHE_SIZE = 1000  # 缓存条目数
CACHE_TTL = 3600  # 缓存有效期（秒）

# 配置日志
logging.basicConfig(
    level=logging.INFO,  # 从DEBUG改为INFO减少输出
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        # 移除FileHandler
        # logging.FileHandler("stream_app.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 加载环境变量（如果有）
load_dotenv()

# 配置 OpenAI (用于 DeepSeek 接口)
openai.api_key = DeepSeekConfig.API_KEY or os.getenv("DEEPSEEK_API_KEY")
openai.api_base = DeepSeekConfig.API_BASE or os.getenv("DEEPSEEK_API_BASE")

redis_client = redis.Redis(host='localhost', port=6379, db=0)

class Translator:
    """翻译类"""
    
    def __init__(self):
        self.client = OpenAI(
            api_key=DeepSeekConfig.API_KEY,
            base_url=DeepSeekConfig.API_BASE
        )
        self.model = DeepSeekConfig.MODEL_NAME
        self.cache = {}  # 内存缓存字典
        self.last_cache_clean = datetime.now()
        self.cache_hits = 0
        self.cache_misses = 0
    
    def detect_language(self, text):
        """检测语言"""
        try:
            # 优化语言检测逻辑
            lang = detect(text)
            # 扩展中文变体识别
            if lang.startswith('zh'):
                return 'chinese'
            # 增加越南语识别
            if lang in ['vi', 'vie']:
                return 'vietnamese'
            return lang
        except Exception as e:
            logger.warning(f"语言检测失败: {text[:30]}... 错误: {str(e)}")
            return 'unknown'
    
    def _get_cache_key(self, text: str, source_lang: str) -> str:
        """生成唯一缓存键"""
        return hashlib.md5(f"{source_lang}_{text}".encode('utf-8')).hexdigest()

    @lru_cache(maxsize=CACHE_SIZE)
    def _cached_translation(self, text: str, source_lang: str) -> Optional[str]:
        """带LRU缓存的翻译方法"""
        key = self._get_cache_key(text, source_lang)
        # 自动清理过期缓存
        if (datetime.now() - self.last_cache_clean).seconds > 300:
            self._clean_cache()
        return self.cache.get(key)

    def _clean_cache(self):
        """清理过期缓存"""
        now = datetime.now()
        self.cache = {k: v for k, v in self.cache.items() if now < v['expire_time']}
        self.last_cache_clean = now

    def translate(self, text, source_lang=None):
        """带缓存的翻译方法"""
        if source_lang is None:
            source_lang = self.detect_language(text)
        
        # 新增调试日志
        logger.debug(f"检测到语言: {source_lang} | 原文: {text[:50]}...")
        
        # 强制设置翻译方向（当检测失败时）
        if source_lang not in ['chinese', 'vietnamese']:
            logger.warning(f"无法识别的语言，默认按中译越处理 | 原文: {text[:50]}...")
            source_lang = 'chinese'  # 默认处理为中文
        
        # 检查缓存
        cache_key = self._get_cache_key(text, source_lang)
        cached = self.cache.get(cache_key)
        if cached and datetime.now() < cached['expire_time']:
            logger.debug("命中缓存")
            self.cache_hits += 1
            return cached['result'], source_lang
        
        target_lang = 'vietnamese' if source_lang == 'chinese' else 'chinese'
        
        try:
            prompt = self._get_translation_prompt(text, source_lang, target_lang)
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的翻译助手，需要准确翻译用户的文本。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2048
            )
            
            translated_text = response.choices[0].message.content.strip()
            
            # 优化结果清洗逻辑
            markers = ["翻译如下", "以下是翻译结果", "Translation:"]
            for marker in markers:
                if marker in translated_text:
                    translated_text = translated_text.split(marker, 1)[-1].strip()
                    break
            
            logger.debug(f"原文长度: {len(text)}, 译文长度: {len(translated_text)}")  # 新增调试信息
            
            # 存储结果到缓存
            self.cache[cache_key] = {
                'result': translated_text,
                'expire_time': datetime.now() + timedelta(seconds=CACHE_TTL)
            }
            self.cache_misses += 1
            return translated_text, source_lang
        
        except Exception as e:
            logger.error(f"翻译失败: {e}")
            return f"翻译失败: {e}", source_lang
    
    def _get_translation_prompt(self, text, source_lang, target_lang):
        """获取翻译提示"""
        if source_lang == 'chinese' and target_lang == 'vietnamese':
            return f"请将以下中文文本准确翻译成越南语，保持原文的语气和风格:\n\n{text}"
        elif source_lang == 'vietnamese' and target_lang == 'chinese':
            return f"请将以下越南语文本准确翻译成中文，保持原文的语气和风格:\n\n{text}"
        else:
            return f"请将以下{source_lang}文本翻译成{target_lang}:\n\n{text}"


class TranslatorChatbotHandler(ChatbotHandler):
    """钉钉Stream模式聊天机器人消息处理器"""
    
    def __init__(self):
        super().__init__()  # 使用正确父类初始化
        self.translator = Translator()
        self.processed_messages = deque(maxlen=1000)  # 限制缓存大小防止内存泄漏
        self.rate_limits = {}  # 用户速率限制记录
        logger.info("钉钉中越翻译机器人已初始化")

    # 新增pre_start方法
    def pre_start(self):
        """SDK要求的初始化方法"""
        pass

    async def process(self, data) -> AckMessage:
        """处理接收到的消息"""
        try:
            # 确保获取到正确的消息对象
            if isinstance(data, dingtalk_stream.CallbackMessage):
                raw_data = data.data
                message = ChatbotMessage.from_dict(raw_data)
            else:
                message = ChatbotMessage.from_dict(data)
            
            # 先处理消息ID去重 (调整到最前面)
            message_id = message.message_id
            if message_id in self.processed_messages:
                return AckMessage.STATUS_OK, "重复消息已忽略"
            self.processed_messages.append(message_id)  # 修改为append
            
            logger.debug(f"原始回调数据: {message.to_dict()}")

            # 移除@用户提取和处理逻辑
            content = message.text.content.replace("@翻译机器人", "").strip()
            
            if not content:
                await self.reply_text("请输入需要翻译的文本")
                return AckMessage.STATUS_OK, "请输入需要翻译的文本"
            
            # 速率限制检查（新增）
            user_id = message.sender_staff_id
            if self._check_rate_limit(user_id):
                await self.reply_text("请求过于频繁，请稍后再试", incoming_message=message)
                return AckMessage.STATUS_OK, "速率限制"
            
            # 重构翻译流程
            translation_task = asyncio.create_task(
                self._handle_translation(content, message)
            )
            await translation_task
            
            return AckMessage.STATUS_OK, "成功处理消息"
            
        except openai.OpenAIError as e:  # 特定异常处理
            await self.reply_text("连接翻译服务失败，请稍后重试", incoming_message=message)
            logger.error(f"API连接异常: {e}")
        except Exception as e:
            logger.error(f"消息处理失败: {str(e)}", exc_info=True)  # 记录完整堆栈
            await self.reply_text("消息解析失败，请尝试重新发送", incoming_message=message)
            return AckMessage.STATUS_FAIL, str(e)

    async def _handle_translation(self, content, message):
        """独立处理翻译流程"""
        translated_text, _ = await asyncio.to_thread(
            self.translator.translate, content
        )
        
        # 直接回复翻译结果
        result = self.reply_text(
            text=translated_text,  # 直接使用翻译结果
            incoming_message=message
        )
        if asyncio.iscoroutine(result):
            await result

    def bind_client(self, client):
        self.dingtalk_client = client  # 显式绑定客户端
        return self  # 支持链式调用

    def _check_rate_limit(self, user_id: str) -> bool:
        """速率限制检查（滑动窗口算法）"""
        now = datetime.now()
        window_start = now - timedelta(minutes=1)
        
        # 清理过期记录
        self.rate_limits[user_id] = [
            t for t in self.rate_limits.get(user_id, []) 
            if t > window_start
        ]
        
        # 添加新请求并检查数量
        self.rate_limits[user_id].append(now)
        return len(self.rate_limits[user_id]) > RATE_LIMIT


async def main_async():
    """Stream模式主函数"""
    logger.info("正在启动钉钉中越翻译机器人...")
    
    # 获取应用配置
    app_key = DingTalkConfig.APP_KEY or os.getenv("DINGTALK_APP_KEY")
    app_secret = DingTalkConfig.APP_SECRET or os.getenv("DINGTALK_APP_SECRET")
    
    if not app_key or not app_secret:
        logger.error("请配置钉钉应用的 APP_KEY 和 APP_SECRET")
        return
    
    # 使用最新SDK推荐方式
    client = DingTalkStreamClient(
        credential=dingtalk_stream.Credential(app_key, app_secret),
        logger=logger
    )
    
    # 创建处理器实例并显式绑定客户端
    handler = TranslatorChatbotHandler()
    client.register_callback_handler(
        dingtalk_stream.ChatbotMessage.TOPIC,
        handler  # 直接传递handler
    )
    
    # 使用安全启动方式
    try:
        await client.start()
        logger.info("✅ 客户端已成功启动")
        while True:  # 保持事件循环运行
            await asyncio.sleep(3600)
    except ConnectionClosedError as e:
        logger.error(f"连接异常关闭: {e.code} - {e.reason}")
    except Exception as e:
        # 修正日志参数格式
        logger.exception("客户端运行异常: %s", str(e))
    finally:
        logger.info("🛑 客户端已停止")

def main():
    # 强制设置Windows事件循环策略
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # 创建新事件循环
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(main_async())
    except KeyboardInterrupt:
        logger.info("👋 用户主动终止程序")
    finally:
        loop.close()

if __name__ == "__main__":
    main() 

class DingTalkStreamClient(dingtalk_stream.DingTalkStreamClient):
    async def on_connected(self):
        logger.info("✅ 已成功连接到钉钉服务器")
        
    async def on_disconnected(self):
        logger.error("❌ 连接断开，尝试重新连接...")
        await asyncio.sleep(5)
        await self.start()  # 自动重连机制

    async def on_error(self, exception):
        logger.error(f"WebSocket错误: {type(exception).__name__}")
        if isinstance(exception, websockets.exceptions.ConnectionClosedError):
            logger.error(f"连接关闭原因: {exception.code} - {exception.reason}") 