from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from sharing.models import ShareInvite
from tasks.models import Task

from .models import Notification

STUDY_TIPS = [
    "Use active recall: close notes and explain what you remember.",
    "Study in 25-minute blocks and take a short break after each block.",
    "Teach the topic out loud. If it feels hard, that is exactly where to focus.",
    "Start with your hardest topic while your energy is still high.",
    "Review yesterday's topic for 10 minutes before starting a new one.",
    "Write one mini-goal before each study session and check it off after.",
]

MOTIVATION_LINES = [
    "Small sessions done consistently beat long sessions done rarely.",
    "Progress today makes exam pressure lower tomorrow.",
    "You do not need perfect notes. You need clear understanding.",
    "One focused hour now can save many hours later.",
]


def _notification_settings():
    due_soon_minutes = max(1, int(getattr(settings, "NOTIFICATIONS_TASK_DUE_SOON_MINUTES", 15)))
    study_minutes = max(10, int(getattr(settings, "NOTIFICATIONS_STUDY_REMINDER_MINUTES", 90)))
    return due_soon_minutes, study_minutes


def create_notification(
    *,
    user,
    kind,
    title,
    message,
    data=None,
    source_key=None,
    created_at=None,
):
    payload = data or {}
    if source_key:
        defaults = {
            "kind": kind,
            "title": title,
            "message": message,
            "data": payload,
        }
        if created_at:
            defaults["created_at"] = created_at

        try:
            instance, _ = Notification.objects.get_or_create(
                user=user,
                source_key=source_key,
                defaults=defaults,
            )
            return instance
        except IntegrityError:
            return Notification.objects.filter(user=user, source_key=source_key).first()

    return Notification.objects.create(
        user=user,
        kind=kind,
        title=title,
        message=message,
        data=payload,
    )


def sync_notifications_for_user(user):
    now = timezone.now()
    due_soon_minutes, study_minutes = _notification_settings()
    due_soon_cutoff = now + timedelta(minutes=due_soon_minutes)

    pending_invites = ShareInvite.objects.filter(
        invited_user=user,
        status="pending",
    ).select_related("invited_by", "share")
    for invite in pending_invites:
        resource = invite.share.resource_type if invite.share_id else "resource"
        create_notification(
            user=user,
            kind=Notification.KIND_SHARE_INVITE,
            title="New Share Invite",
            message=f"{invite.invited_by.username} invited you to a {resource}.",
            data={
                "invite_id": invite.id,
                "resource_type": resource,
                "share_token": str(invite.share_id) if invite.share_id else "",
            },
            source_key=f"share-invite:{invite.id}",
            created_at=invite.created_at,
        )

    due_tasks = Task.objects.filter(
        user=user,
        is_completed=False,
        due_date__isnull=False,
        due_date__lte=due_soon_cutoff,
    ).only("id", "title", "due_date")

    for task in due_tasks:
        if task.due_date <= now:
            create_notification(
                user=user,
                kind=Notification.KIND_TASK_DUE,
                title="Task Due",
                message=f"{task.title} reached its due time.",
                data={"task_id": task.id},
                source_key=f"task-due:{task.id}",
                created_at=task.due_date,
            )
        else:
            create_notification(
                user=user,
                kind=Notification.KIND_TASK_DUE_SOON,
                title="Task Due Soon",
                message=f"{task.title} is due soon at {timezone.localtime(task.due_date).strftime('%Y-%m-%d %H:%M')}.",
                data={"task_id": task.id},
                source_key=f"task-due-soon:{task.id}",
                created_at=task.due_date,
            )

    slot_seconds = study_minutes * 60
    slot = int(now.timestamp() // slot_seconds)
    tip = STUDY_TIPS[slot % len(STUDY_TIPS)]
    motivation = MOTIVATION_LINES[slot % len(MOTIVATION_LINES)]

    create_notification(
        user=user,
        kind=Notification.KIND_STUDY_REMINDER,
        title="Study Reminder",
        message=f"{motivation} Tip: {tip}",
        data={},
        source_key=f"study-reminder:{slot}",
    )

