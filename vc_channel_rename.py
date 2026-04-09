"""
VC（ボイスチャンネル）の名前に「(ポモ中)」を付けたり戻したりする処理。

無効時は一切 API を呼ばない。.env で POMODORO_RENAME_VC_CHANNEL=1 とすると有効。
"""

from __future__ import annotations

import asyncio
import os

import discord
from discord.errors import RateLimited

__all__ = (
    "is_vc_channel_rename_enabled",
    "try_edit_voice_channel_name",
    "ensure_pomodoro_prefix_name",
    "restore_vc_channel_name_by_id",
    "restore_vc_channel_if_pomodoro_tag",
)


def is_vc_channel_rename_enabled() -> bool:
    """環境変数 POMODORO_RENAME_VC_CHANNEL が 1/true/yes/on のときだけ True（既定は無効）。"""
    v = os.getenv("POMODORO_RENAME_VC_CHANNEL", "").strip().lower()
    return v in ("1", "true", "yes", "on")


async def try_edit_voice_channel_name(
    channel: discord.abc.GuildChannel,
    new_name: str,
) -> bool:
    """チャンネル名を変更する。機能オフ時は何もせず True。429 等はスキップしてタイマーに影響させない。"""
    if not is_vc_channel_rename_enabled():
        return True
    if getattr(channel, "name", None) == new_name:
        return True
    try:
        await asyncio.wait_for(channel.edit(name=new_name), timeout=10.0)
        return True
    except asyncio.CancelledError:
        raise
    except (asyncio.TimeoutError, RateLimited):
        return False
    except discord.HTTPException as e:
        if e.status == 429:
            return False
        raise


async def ensure_pomodoro_prefix_name(
    guild: discord.Guild,
    channel_id: int,
    original_channel_name: str,
) -> None:
    """作業セッションのたびに (ポモ中) 接頭辞を付ける。無効時は no-op。"""
    if not is_vc_channel_rename_enabled():
        return
    current = guild.get_channel(channel_id)
    if current is None:
        current = await guild.fetch_channel(channel_id)
    if current is None:
        return
    new_name = f"(ポモ中){original_channel_name}"
    if current.name != new_name:
        await try_edit_voice_channel_name(current, new_name)


async def restore_vc_channel_name_by_id(
    guild: discord.Guild,
    channel_id: int,
    original_channel_name: str,
) -> None:
    """チャンネル ID 指定で元の名前に戻す。無効時は no-op。"""
    if not is_vc_channel_rename_enabled():
        return
    ch = guild.get_channel(channel_id)
    if ch is None:
        ch = await guild.fetch_channel(channel_id)
    if ch is not None:
        await try_edit_voice_channel_name(ch, original_channel_name)


async def restore_vc_channel_if_pomodoro_tag(channel: discord.abc.GuildChannel) -> None:
    """名前に (ポモ中) が含まれるときだけ元名へ。停止ボタン用。無効時は no-op。"""
    if not is_vc_channel_rename_enabled():
        return
    if "(ポモ中)" not in channel.name:
        return
    original_name = channel.name.replace("(ポモ中)", "").strip()
    target = original_name or channel.name
    await try_edit_voice_channel_name(channel, target)
