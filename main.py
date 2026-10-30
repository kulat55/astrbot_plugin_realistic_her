# -*- coding: utf-8 -*-
"""真人化增强插件：补全林小瞒 16 项真人感功能。

主动类（后台调度，复用生图/天气/记忆基建）：
  1. 失联反应：好几天没联系，她开口先问"怎么没找我"
  2. 反向查岗：会话冷下来之后反过来问你"在干嘛"
  3. 天气感知：早上主动聊天气（open-meteo，无 key）
  4. 爱好进展：追剧/看书进度持续推进，隔几天聊一次
  5. 主动发图：随机"随手拍"发图（本地 Stable Diffusion）
  6. 熬夜提醒：深夜你还在线，她催你睡
  7. 重要日子：/记住 存的日子到点主动提
  8. 情绪关心：你心情不好/吵架后，她隔天主动关心

对话类（回复后追加）：
  9. 翻旧账："你上次不是说……"（本地记录关键约定）
  10. 吃醋：你提到异性/别人时微妙反应
  11. 猜你作息：按你回复时段调侃（半夜/午休/上班）
  12. 表情包：追加时偶尔带张图（预制萌系表情）

命令类：
  13. /记住 <日期> <事> —— 存重要日子，到点主动提
  14. /约定 <时间> <事> —— 存承诺，到点提醒
  15. /猜拳 —— 石头剪刀布
  16. /真心话 [问题] —— 她出题或答题
"""
import asyncio
import base64
import json
import os
import random
import time
import urllib.request
from datetime import datetime, timedelta

from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Record
from astrbot.api.star import Context, Star
from astrbot.core.star.filter.command import GreedyStr

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_EMOTE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images", "emotes")
_SD_SERVER = "http://127.0.0.1:7862/draw"
_WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=31.3&longitude=120.6&current=temperature_2m,weather_code,relative_humidity_2m"
    "&timezone=Asia%2FShanghai"
)
_LLM_URL = "https://api.deepseek.com/v1/chat/completions"
_CMD_CONFIG = (
    r"E:\baidu-game\.astrbot_launcher\instances\25f834dc-196f-4440-a6b3-521e69112129"
    r"\core\data\cmd_config.json"
)
_PLANS_FILE = (
    r"E:\baidu-game\.astrbot_launcher\instances\25f834dc-196f-4440-a6b3-521e69112129"
    r"\core\data\plugin_data\astrbot_plugin_virtual_life\plans.json"
)
_PERSONA = (
    "你是林小瞒，一个二十多岁、有点小性子但很真实的女生，和好友聊天。"
    "说话口语化，简短自然，带一点撒娇和调侃，不用敬语，不发长篇大论。"
    "只输出消息正文，不要任何解释或前缀。"
)

_WEATHER_TEXT = {
    0: "大晴天", 1: "大部晴朗", 2: "有点多云", 3: "阴天",
    45: "有雾", 48: "雾大", 51: "毛毛雨", 53: "小雨", 55: "阵雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "大雨", 82: "暴雨", 85: "阵雪", 86: "大雪",
    95: "雷阵雨", 96: "雷阵雨带冰雹", 99: "雷暴冰雹",
}

_TEASE_WORDS = ("胖", "肥", "猪", "傻", "笨", "蠢", "菜", "弱", "懒", "丑", "矮")
_RETORT_MARKS = ("才是", "才不", "我这是", "正常", "胡说", "哪有", "谁说的", "你才", "才怪")
_JEALOUSY_WORDS = ("女生", "男生", "小姐姐", "小哥哥", "同事", "朋友", "闺蜜", "兄弟", "她", "他")
_NIGHT_RECALL = (
    "这个点了还不睡？小心明天起不来。",
    "半夜不睡觉，你是夜猫子本猫吧。",
    "都几点了还精神，明天上班别怪我早上没叫你。",
    "你该不会又熬夜打游戏了吧？",
)
_LUNCH_RECALL = ("这个点你不好好吃饭，摸鱼呢？", "午休时间还在回消息，你们公司管这么松？")
_MORNING_RECALL = ("一大早就给我发消息，今天这么勤快？", "这么早，你是不是还没睡醒？")
_FORGOTTEN_OLDS = (
    "你上次还说请我吃饭呢，什么时候兑现啊？",
    "你那天不是说要早点睡的吗，现在几点了？",
    "上次你说的那个事，后来怎么样了？",
    "你之前答应我的可别忘了啊。",
    "我记得你说过再也不熬夜的，对吧？",
)
_JEALOUSY_RECALL = (
    "哦？男的还是女的？",
    "你朋友圈里那个是谁啊？",
    "天天跟别人聊天，都不理我了。",
    "哼，你说的那个朋友，我怎么没听你提过。",
    "行吧，那你去找他/她聊呗。",
)
_ROCK_PAPER = ("石头", "剪刀", "布")
_TRUTH_QUESTIONS = (
    "你最近一次撒谎是什么时候？",
    "你手机里最不想让人看到的 app 是哪个？",
    "你有没有偷偷查过前任的动态？",
    "你银行卡里现在大概有多少钱？",
    "你做过最后悔的一件事是什么？",
    "你有没有背着朋友吐槽过他们？",
    "你理想中的另一半是什么样的？",
)


def _read_deepseek_key() -> str | None:
    """从 AstrBot cmd_config 读取 deepseek key（值绝不外泄）。"""
    try:
        with open(_CMD_CONFIG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for src in cfg.get("provider_sources", []):
            keys = src.get("key", [])
            if src.get("provider", "") == "deepseek" and keys:
                return str(keys[0])
    except Exception:
        pass
    return None


def _read_tts_config() -> dict | None:
    """从 AstrBot cmd_config 读取豆包语音配置（值绝不外泄）。"""
    try:
        with open(_CMD_CONFIG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for src in cfg.get("provider_sources", []):
            if src.get("type", "") == "seed_audio_tts" and src.get("app_id"):
                return {
                    "app_id": str(src["app_id"]),
                    "access_key": str(src.get("access_key", "")),
                    "api_base": str(src.get("api_base", "") or
                                    "https://openspeech.bytedance.com/api/v3/tts/create"),
                    "resource_id": str(src.get("resource_id", "") or "seed-audio-1.0"),
                    "model": str(src.get("model", "") or "seed-audio-1.0"),
                }
    except Exception:
        pass
    return None


def _now() -> datetime:
    return datetime.now()


class RealisticHerPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        os.makedirs(_DATA, exist_ok=True)
        os.makedirs(_EMOTE_DIR, exist_ok=True)
        self._mem_file = os.path.join(_DATA, "state.json")
        self._state = self._load_state()
        self._pending_follow = {}   # umo -> 追加文本
        self._pending_emote = {}    # umo -> 表情包标记
        self._loop_task = None

    # ---------- 状态存储 ----------
    def _load_state(self) -> dict:
        try:
            with open(self._mem_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {
                "sessions": {},      # umo -> {last_user_at, last_proactive_at, sent_today}
                "reminders": [],     # {target, text, kind}
                "hobbies": {},       # persona -> {type, progress, updated_at}
                "moods": {},         # umo -> {bad_at, reason, cared_at}
                "notes": [],         # {text, at}
                "emotes": [],        # 表情图路径
            }

    def _save_state(self) -> None:
        try:
            with open(self._mem_file, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    # ---------- 通用工具 ----------
    def _session(self, umo: str) -> dict:
        return self._state["sessions"].setdefault(umo, {
            "last_user_at": _now().isoformat(),
            "last_proactive_at": "",
            "sent_today": 0,
            "date": _now().date().isoformat(),
        })

    def _is_sleeping(self) -> bool:
        """读虚拟人生当日日程，判断当前时段是否 sleep。"""
        try:
            today = _now().date().isoformat()
            with open(_PLANS_FILE, "r", encoding="utf-8") as f:
                plans = json.load(f).get("plans", {})
            for key, plan in plans.items():
                if not str(key).startswith(today):
                    continue
                now_min = _now().hour * 60 + _now().minute
                for item in plan.get("timeline", []):
                    start = item.get("start", "")
                    end = item.get("end", "")
                    if ":" not in start or ":" not in end:
                        continue
                    sh, sm = map(int, start.split(":"))
                    eh, em = map(int, end.split(":"))
                    if sh * 60 + sm <= now_min < eh * 60 + em:
                        return item.get("state") == "sleep"
            return False
        except Exception:
            return False

    def _plan_context(self) -> str:
        """读虚拟人生当日日程，返回当前状态上下文，让主动消息与人设一致。"""
        try:
            today = _now().date().isoformat()
            with open(_PLANS_FILE, "r", encoding="utf-8") as f:
                plans = json.load(f).get("plans", {})
            plan = None
            for key, p in plans.items():
                if str(key).startswith(today):
                    plan = p
                    break
            if not plan:
                return "（今天还没有日程安排，别编造你在做什么或在哪）"
            if plan.get("status") == "failed" or not plan.get("timeline"):
                return "（今天你的日程没生成出来，别编造你在做什么、在哪、吃什么）"
            now_min = _now().hour * 60 + _now().minute
            for item in plan.get("timeline", []):
                start = item.get("start", "")
                end = item.get("end", "")
                if ":" not in start or ":" not in end:
                    continue
                sh, sm = map(int, start.split(":"))
                eh, em = map(int, end.split(":"))
                if sh * 60 + sm <= now_min < eh * 60 + em:
                    if item.get("state") == "sleep":
                        return "（你现在在睡觉）"
                    act = item.get("activity", "")
                    loc = item.get("location", "")
                    state = f"你现在正在{act}" if act else "你正在进行今天的安排"
                    if loc:
                        state += f"，在{loc}"
                    return f"（{state}）"
            return ""
        except Exception:
            return ""

    def _vl_recent_proactive(self, now: datetime, minutes: int = 45) -> bool:
        """虚拟人生最近是否刚发过主动消息；在窗口内主动谦让，避免双系统撞车。"""
        try:
            fp = os.path.join(os.path.dirname(_PLANS_FILE), "sessions.json")
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            for sess in data.get("sessions", {}).values():
                last = sess.get("last_proactive_at", "")
                if not last:
                    continue
                dt = datetime.fromisoformat(last)
                if dt.tzinfo:
                    dt = dt.astimezone().replace(tzinfo=None)
                if (now - dt).total_seconds() / 60 < minutes:
                    return True
            return False
        except Exception:
            return False

    def _llm_text(self, prompt: str, max_tokens: int = 200) -> str | None:
        """调用 deepseek-chat 生成文本。"""
        key = _read_deepseek_key()
        if not key:
            return None
        try:
            body = json.dumps({
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": _PERSONA},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.9,
            }).encode("utf-8")
            req = urllib.request.Request(
                _LLM_URL, data=body,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data["choices"][0]["message"]["content"].strip()
            return text[:200]
        except Exception:
            return None

    def _weather_now(self) -> str | None:
        try:
            with urllib.request.urlopen(_WEATHER_URL, timeout=10) as resp:
                d = json.loads(resp.read().decode("utf-8"))
            cur = d.get("current", {})
            temp = cur.get("temperature_2m")
            code = cur.get("weather_code")
            desc = _WEATHER_TEXT.get(code, "不知道什么天")
            if temp is None:
                return None
            return f"{desc}，{temp:.0f}°C"
        except Exception:
            return None

    async def _draw_and_send(self, umo: str, prompt: str) -> bool:
        """调本地生图服务并发送图片。"""
        try:
            payload = json.dumps({"prompt": prompt, "width": 512, "height": 512}).encode("utf-8")
            req = urllib.request.Request(_SD_SERVER, data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if "image" not in data:
                return False
            path = os.path.join(_DATA, f"snap_{int(time.time())}.png")
            with open(path, "wb") as f:
                f.write(base64.b64decode(data["image"]))
            await self.context.send_message(umo, MessageChain().message(
                self._image_segment(path)))
            return True
        except Exception:
            return False

    def _image_segment(self, path: str):
        from astrbot.api.message_components import Image
        return Image(file=path)

    async def _send(self, umo: str, text: str) -> bool:
        try:
            await self.context.send_message(umo, MessageChain().message(text))
            return True
        except Exception:
            return False

    async def _send_maybe_voice(self, umo: str, text: str) -> bool:
        """主动消息：15% 概率转成语音发，像她懒得打字。"""
        if random.random() < 0.15:
            path = await self._tts_audio(text)
            if path:
                try:
                    await self.context.send_message(
                        umo, MessageChain().message(Record(file=path, url=path, text=text)))
                    return True
                except Exception:
                    pass
        return await self._send(umo, text)

    async def _tts_audio(self, text: str) -> str | None:
        """调豆包 Seed Audio 生成 mp3，返回本地路径。"""
        cfg = _read_tts_config()
        if not cfg:
            return None
        try:
            import aiohttp
            import uuid
            body = json.dumps({
                "model": cfg["model"],
                "text_prompt": (
                    "一个二十多岁的普通女生，给好朋友发微信语音时那样说话，"
                    "声音自然有温度，语气跟着内容走，口语化。只念这句：“" + text + "”"
                ),
                "audio_config": {"format": "mp3", "sample_rate": 24000,
                                 "enable_subtitle": True},
            }, ensure_ascii=False).encode("utf-8")
            headers = {
                "X-Api-App-Id": cfg["app_id"],
                "X-Api-Access-Key": cfg["access_key"],
                "X-Api-Resource-Id": cfg["resource_id"],
                "X-Api-Request-Id": str(uuid.uuid4()),
                "Content-Type": "application/json",
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    cfg["api_base"], data=body, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    raw = await resp.text()
            data = json.loads(raw)
            if resp.status != 200 or not data.get("audio"):
                return None
            path = os.path.join(_DATA, f"voice_{int(time.time())}.mp3")
            with open(path, "wb") as f:
                f.write(base64.b64decode(data["audio"]))
            return path
        except Exception:
            return None

    def _parse_reminder_time(self, target: str, now: datetime) -> datetime | None:
        """解析 /约定 的自然时间：明早8点 / 今晚10点 / 8点30 / 8点 → 具体时间。"""
        import re
        t = str(target).strip()
        hour = minute = None
        is_night = False
        m = re.search(r"(明早|明晚|明|今晚|今天|早上|晚上)?\s*(\d{1,2})\s*[:：]\s*(\d{1,2})", t)
        if m:
            hour, minute = int(m.group(2)), int(m.group(3))
        else:
            m = re.search(r"(明早|明晚|明|今晚|今天|早上|晚上)?\s*(\d{1,2})\s*点\s*(\d{1,2})?", t)
            if m:
                hour, minute = int(m.group(2)), int(m.group(3) or 0)
        if hour is None or not (0 <= hour <= 23):
            return None
        if minute is None:
            minute = 0
        # "今晚/明晚" + 12 以内的小时 → 晚上时间
        if ("晚" in t and ("今" in t or "明" in t)) and 1 <= hour <= 12:
            hour += 12
        day_offset = 0
        if "明" in t and "今" not in t:
            day_offset = 1
        dt = now + timedelta(days=day_offset)
        dt = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if dt <= now:
            dt += timedelta(days=1)
        return dt

    async def _check_reminder_times(self, umo: str, now: datetime) -> bool:
        """到点的 /约定 提醒（每个提醒每天只提醒一次）。"""
        sent = False
        today = now.date().isoformat()
        for rem in self._state["reminders"]:
            if rem.get("kind") != "reminder":
                continue
            if rem.get("sent_at", "") == today:
                continue
            target_dt = self._parse_reminder_time(rem.get("target", ""), now)
            if not target_dt:
                continue
            if target_dt.date() == now.date() and target_dt.hour == now.hour \
                    and now.minute < 10 and target_dt <= now + timedelta(minutes=10):
                text = self._llm_text(
                    f"你答应过的事到点了：{rem.get('text')}（约的{rem.get('target')}），"
                    f"发条消息提醒他，自然一点。"
                ) or f"到点了哦：{rem.get('text')}"
                if await self._send_maybe_voice(umo, text):
                    rem["sent_at"] = today
                    sent = True
                    self._save_state()
        return sent

    # ---------- 主动调度 ----------
    async def _proactive_loop(self) -> None:
        while True:
            try:
                await self._check_proactive()
            except Exception:
                pass
            await asyncio.sleep(20 * 60)

    async def _check_proactive(self) -> None:
        now = _now()
        plan_ctx = self._plan_context()
        sessions = list(self._state["sessions"].items())
        for umo, sess in sessions:
            if "FriendMessage" not in umo:
                continue
            today = now.date().isoformat()
            if sess.get("date") != today:
                sess["date"] = today
                sess["sent_today"] = 0
            if sess["sent_today"] >= 2:
                continue
            if self._is_sleeping():
                continue
            # /约定 到点提醒（独立于条数限制，不打扰睡眠时段）
            if 7 <= now.hour < 23 and await self._check_reminder_times(umo, now):
                sess["sent_today"] += 1
                self._save_state()
                continue
            # 虚拟人生刚发过主动消息（45 分钟内）：谦让，避免双主动撞车人设矛盾
            if self._vl_recent_proactive(now, 45):
                continue
            last_user = sess.get("last_user_at", "")
            if not last_user:
                continue
            last_dt = datetime.fromisoformat(last_user)
            idle_hours = (now - last_dt).total_seconds() / 3600

            # 1. 失联反应：>=48 小时没联系，每天最多一次
            if idle_hours >= 48 and sess.get("last_missing_at", "") != today:
                text = self._llm_text(
                    f"{plan_ctx}你好几天没找我了，现在想发一条消息给他，有点小情绪但不说太重的话。"
                    f"（最近一次联系是 {int(idle_hours)} 小时前）"
                ) or "这几天怎么没找我？我还以为你人间蒸发了。"
                if await self._send_maybe_voice(umo, text):
                    sess["last_missing_at"] = today
                    sess["sent_today"] += 1
                    sess["last_proactive_at"] = now.isoformat()
                    self._save_state()
                    continue

            # 2. 反向查岗：空闲 3-12 小时，每天 0-1 次
            if 3 <= idle_hours <= 12 and random.random() < 0.35:
                text = self._llm_text(
                    f"{plan_ctx}现在 {now.strftime('%H:%M')}，你半天没找我，我发条消息问你在干嘛，自然一点。"
                ) or "在干嘛呢？半天没动静。"
                if await self._send_maybe_voice(umo, text):
                    sess["sent_today"] += 1
                    sess["last_proactive_at"] = now.isoformat()
                    self._save_state()
                    continue

            # 3. 天气感知：每天一次（早上 8-10 点）
            if 8 <= now.hour <= 10 and sess.get("last_weather_at", "") != today:
                weather = self._weather_now()
                if weather:
                    text = self._llm_text(
                        f"{plan_ctx}现在外面{weather}，你随口说一句天气感受，只聊天气本身，"
                        f"别说自己正在做什么、要去哪、在吃什么。"
                    ) or f"今天{weather}，出门记得看天气啊。"
                    if await self._send_maybe_voice(umo, text):
                        sess["last_weather_at"] = today
                        sess["sent_today"] += 1
                        self._save_state()
                        continue

            # 4. 熬夜提醒：深夜时段
            if 23 <= now.hour or now.hour < 2:
                if random.random() < 0.6 and sess.get("last_night_at", "") != today:
                    if await self._send_maybe_voice(umo, random.choice(_NIGHT_RECALL)):
                        sess["last_night_at"] = today
                        sess["sent_today"] += 1
                        self._save_state()
                        continue

            # 5. 爱好进展：每 2 天一次
            hobby = self._state["hobbies"].get("林小瞒", {})
            if hobby:
                last_h = hobby.get("updated_at", "")
                if (not last_h or (now - datetime.fromisoformat(last_h)).days >= 2
                        and random.random() < 0.6):
                    hobby["progress"] += 1
                    hobby["updated_at"] = now.isoformat()
                    text = self._llm_text(
                        f"{plan_ctx}你最近在{hobby.get('type', '追剧')}，进度到{hobby.get('progress')}了，"
                        f"主动跟朋友聊一句你的爱好进展。"
                    )
                    if text and await self._send_maybe_voice(umo, text):
                        self._save_state()
                        continue

            # 6. 重要日子：到点主动提
            today_str = f"{now.month}月{now.day}日"
            for rem in self._state["reminders"]:
                if rem.get("kind") == "date" and rem.get("target") == today_str \
                        and rem.get("sent_at", "") != today:
                    text = self._llm_text(
                        f"{plan_ctx}今天是特别的日子：{rem.get('text')}，你发条消息跟他说，带点在意。"
                    ) or f"今天是不是{rem.get('text')}？我记着的。"
                    if await self._send_maybe_voice(umo, text):
                        rem["sent_at"] = today
                        sess["sent_today"] += 1
                        self._save_state()
                        continue

            # 7. 情绪关心：记录过不开心，次日关心一次
            mood = self._state["moods"].get(umo)
            if mood and mood.get("cared_at", "") != today:
                bad_at = datetime.fromisoformat(mood["bad_at"])
                if (now - bad_at).days >= 1:
                    text = self._llm_text(
                        f"{plan_ctx}他昨天/前几天好像心情不好（{mood.get('reason', '')}），"
                        f"你现在主动关心一下他，别太肉麻。"
                    ) or "昨天看你好像不太开心，现在好点了吗？"
                    if await self._send_maybe_voice(umo, text):
                        mood["cared_at"] = today
                        sess["sent_today"] += 1
                        self._save_state()
                        continue

        # 8. 主动发图：全局每天 0-1 次（在任一活跃会话触发）
        if random.random() < 0.3:
            active = [u for u, s in sessions
                      if "FriendMessage" in u and s.get("sent_today", 0) < 2]
            if active:
                umo = random.choice(active)
                sess = self._session(umo)
                prompt = random.choice([
                    "一个女生随手拍的街边风景，日系滤镜，清新自然",
                    "窗台上一杯咖啡和一本翻开的书，午后阳光",
                    "傍晚的天空，粉色晚霞，手机随手拍",
                    "一只橘猫蹲在台阶上晒太阳",
                ])
                text = self._llm_text(f"{plan_ctx}你随手拍了张照想发给朋友，配一句简单的话。") or "刚随手拍的，好看吗？"
                if await self._draw_and_send(umo, prompt):
                    sess["sent_today"] += 1
                    sess["last_proactive_at"] = _now().isoformat()
                    await asyncio.sleep(1)
                    await self._send(umo, text)
                    self._save_state()

    # ---------- 事件：记录用户活动 ----------
    @filter.on_llm_request(priority=2000)
    async def record_user_activity(self, event: AstrMessageEvent, req) -> None:
        try:
            sess = self._session(event.unified_msg_origin)
            sess["last_user_at"] = _now().isoformat()
            # 情绪识别：用户消息含不开心词
            text = event.message_str or ""
            if any(w in text for w in ("难过", "烦", "累", "生气", "哭了", "难受", "心情不好")):
                self._state["moods"][event.unified_msg_origin] = {
                    "bad_at": _now().isoformat(),
                    "reason": text[:40],
                    "cared_at": "",
                }
                self._save_state()
            # 记录关键约定（翻旧账素材）：用户说"请你/答应你/说好"等
            if any(w in text for w in ("请你", "答应", "说好", "改天请", "欠你")):
                note = {"text": text[:40], "at": _now().isoformat()}
                self._state["notes"].append(note)
                self._state["notes"] = self._state["notes"][-20:]
                self._save_state()
        except Exception:
            pass

    # ---------- 对话追加（翻旧账/吃醋/猜作息/表情包） ----------
    @filter.on_llm_response(priority=2000)
    async def maybe_queue_followup(self, event: AstrMessageEvent, response) -> None:
        try:
            if "FriendMessage" not in event.unified_msg_origin:
                return
            reply = getattr(response, "completion_text", "") or ""
            user_text = event.message_str or ""
            # 斗嘴场景（配合追问补刀插件，这里补表情包）
            if any(w in user_text for w in _TEASE_WORDS) and any(m in reply for m in _RETORT_MARKS):
                if random.random() < 0.25:
                    self._pending_emote[event.unified_msg_origin] = True
                return
            # 吃醋
            if any(w in user_text for w in _JEALOUSY_WORDS) and random.random() < 0.3:
                self._pending_follow[event.unified_msg_origin] = random.choice(_JEALOUSY_RECALL)
                return
            # 猜作息：深夜/午休/清晨 + 概率
            hour = _now().hour
            if 23 <= hour or hour < 2:
                if random.random() < 0.3:
                    self._pending_follow[event.unified_msg_origin] = random.choice(_NIGHT_RECALL)
            elif 12 <= hour <= 14:
                if random.random() < 0.15:
                    self._pending_follow[event.unified_msg_origin] = random.choice(_LUNCH_RECALL)
            elif 6 <= hour <= 8:
                if random.random() < 0.15:
                    self._pending_follow[event.unified_msg_origin] = random.choice(_MORNING_RECALL)
            # 翻旧账：本地记录 + 概率
            if self._state["notes"] and random.random() < 0.12:
                note = random.choice(self._state["notes"])
                text = self._llm_text(
                    f"他之前说过：{note['text']}。你自然地在回复后追问一句这事，别生硬。"
                ) or random.choice(_FORGOTTEN_OLDS)
                self._pending_follow[event.unified_msg_origin] = text
        except Exception:
            pass

    @filter.after_message_sent(priority=2000)
    async def send_followup(self, event: AstrMessageEvent) -> None:
        try:
            umo = event.unified_msg_origin
            if umo in self._pending_follow:
                text = self._pending_follow.pop(umo)
                await asyncio.sleep(random.uniform(1.0, 2.5))
                await self._send(umo, text)
            if umo in self._pending_emote:
                self._pending_emote.pop(umo)
                await asyncio.sleep(random.uniform(0.8, 1.8))
                await self._send_emote(umo)
        except Exception:
            pass

    async def _send_emote(self, umo: str) -> None:
        emotes = [f for f in os.listdir(_EMOTE_DIR)
                  if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
        if not emotes:
            return
        path = os.path.join(_EMOTE_DIR, random.choice(emotes))
        try:
            await self.context.send_message(umo, MessageChain().message(
                self._image_segment(path)))
        except Exception:
            pass

    # ---------- 命令 ----------
    @filter.command("记住")
    async def remember(self, event: AstrMessageEvent, text: GreedyStr) -> None:
        """/记住 <日期> <事情> —— 例：/记住 11月15日 你要考驾照"""
        s = str(text).strip()
        if not s:
            yield event.plain_result("格式：/记住 <日期> <事情>，比如 /记住 11月15日 你要考驾照")
            return
        parts = s.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("格式：/记住 <日期> <事情>")
            return
        self._state["reminders"].append({
            "kind": "date", "target": parts[0], "text": parts[1],
            "sent_at": "", "created_at": _now().isoformat(),
        })
        self._save_state()
        yield event.plain_result(f"记下了：{parts[0]} · {parts[1]}，到那天我会主动提的。")

    @filter.command("约定")
    async def promise(self, event: AstrMessageEvent, text: GreedyStr) -> None:
        """/约定 <时间> <事情> —— 例：/约定 明早8点 叫我起床"""
        s = str(text).strip()
        if not s:
            yield event.plain_result("格式：/约定 <时间> <事情>，比如 /约定 明早8点 叫我起床")
            return
        parts = s.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("格式：/约定 <时间> <事情>")
            return
        self._state["reminders"].append({
            "kind": "reminder", "target": parts[0], "text": parts[1],
            "sent_at": "", "created_at": _now().isoformat(),
        })
        self._save_state()
        yield event.plain_result(f"约好了：{parts[0]} · {parts[1]}，我会记得的。")

    @filter.command("猜拳")
    async def rock_paper(self, event: AstrMessageEvent) -> None:
        """/猜拳 —— 石头剪刀布"""
        mine = random.choice(_ROCK_PAPER)
        yield event.plain_result(f"我出：{mine}")

    @filter.command("真心话")
    async def truth(self, event: AstrMessageEvent, text: GreedyStr | None = None) -> None:
        """/真心话 [问题] —— 她出题问你，或你出题她答"""
        q = str(text).strip() if text else ""
        if q:
            ans = self._llm_text(f"朋友问你真心话：{q}。你老实回答，口语化简短。")
            yield event.plain_result(ans or "让我想想……不太想说，但既然你问了：不告诉你！")
        else:
            yield event.plain_result(f"到我了：{random.choice(_TRUTH_QUESTIONS)}")

    # ---------- 生命周期 ----------
    @filter.on_astrbot_loaded(priority=2000)
    async def start_loop(self) -> None:
        # 初始化默认爱好（没有就建一个追剧进度）
        hobby = self._state["hobbies"].get("林小瞒")
        if not hobby:
            self._state["hobbies"]["林小瞒"] = {
                "type": "追剧", "progress": 3, "updated_at": "",
            }
            self._save_state()
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._proactive_loop())
        # 预生成表情包：后台任务，绝不阻塞 AstrBot 启动
        if not os.listdir(_EMOTE_DIR):
            asyncio.create_task(self._prep_emotes())

    async def _prep_emotes(self) -> None:
        """后台预生成表情包（并发 2 张，失败不阻塞）。"""
        prompts = [
            "可爱的猫猫头表情包风格贴纸，惊讶瞪眼，白色背景",
            "可爱的猫猫头表情包风格贴纸，生气嘟嘴，白色背景",
            "可爱的猫猫头表情包风格贴纸，开心眯眼笑，白色背景",
            "可爱的猫猫头表情包风格贴纸，委屈流泪，白色背景",
            "可爱的猫猫头表情包风格贴纸，得意吐舌，白色背景",
        ]
        sem = asyncio.Semaphore(2)

        async def _one(prompt: str, idx: int) -> None:
            async with sem:
                try:
                    payload = json.dumps(
                        {"prompt": prompt, "width": 512, "height": 512}).encode("utf-8")
                    req = urllib.request.Request(_SD_SERVER, data=payload,
                                                 headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=300) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                    if "image" in data:
                        path = os.path.join(_EMOTE_DIR, f"emote_{idx}.png")
                        with open(path, "wb") as f:
                            f.write(base64.b64decode(data["image"]))
                except Exception:
                    pass

        await asyncio.gather(*[_one(p, i) for i, p in enumerate(prompts)])

    async def terminate(self) -> None:
        if self._loop_task:
            self._loop_task.cancel()
