from datetime import datetime, timedelta

from app.services.scheduler_service import scheduler


async def send_dm(bot, user_id, text):
    try:
        await bot.send_message(chat_id=user_id, text=text)
    except Exception:
        pass


def start_dm_sequence(bot, user_id):

    scheduler.add_job(
        send_dm,
        "date",
        run_date=datetime.utcnow() + timedelta(minutes=1),
        args=[bot, user_id, "🎁 무료 보너스 이벤트 시작!\n지금 바로 참여하세요.\nhttps://example.com"],
    )

    scheduler.add_job(
        send_dm,
        "date",
        run_date=datetime.utcnow() + timedelta(minutes=10),
        args=[bot, user_id, "🔥 아직 참여 안하셨나요?\n보너스가 곧 종료됩니다.\nhttps://example.com"],
    )

    scheduler.add_job(
        send_dm,
        "date",
        run_date=datetime.utcnow() + timedelta(hours=1),
        args=[bot, user_id, "🚀 마지막 기회입니다.\n지금 참여하면 추가 혜택!\nhttps://example.com"],
    )
