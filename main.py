import ast
import inspect
from functools import wraps
import random
import dateutil.parser as dateparser
from dateutil import parser
import zipfile
import json
import os
import pytz
import discord
from discord.ext import commands, tasks
from datetime import datetime, time, timedelta
from dotenv import load_dotenv
import asyncio
from typing import Dict, List, Set, Any, Optional
from discord.ui import View, Button
from flask import Flask
import threading
import shlex
# saldfkjlsdkfjlskdjflksjdf
app = Flask('')


@app.route('/')
def home():
    return "Bot is alive!"


def run():
    app.run(host='0.0.0.0', port=8080)


def keep_alive():
    t = threading.Thread(target=run)
    t.start()


# ========== Setup ==========
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = 1376362880978649098  # Your channel id here
ADMIN_ID = {
    1199446551391633523,  # Admin 1
    931664411255509034,  # Admin 2 
    762376470231908413  # Admin 3
}  # Replace with actual admin user ID
# ========== New Constants ==========
TASK_CHANNEL_ID = 1376362923567612015  # Replace with your task channel ID
REMINDER_DAYS = [7, 5, 3, 2, 1]
MAX_LIVES = 3

EST = pytz.timezone('US/Eastern')
# Color Palette
COLORS = {
    "primary": 0x5865F2,  # Discord blurple
    "success": 0x57F287,  # Discord green
    "warning": 0xFEE75C,  # Discord yellow
    "error": 0xED4245,  # Discord red
    "neutral": 0xEB459E,  # Discord pink
    "dark": 0x23272A,  # Discord dark
    "info": 0x3498db,
    "light": 0xFFFFFF,  # White
    "highlight": 0xF1C40F
}

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.messages = True
intents.guilds = True
intents.members = True


class TaskBot(commands.Bot):

    def __init__(self, *args, **kwargs):
        case_insensitive = kwargs.pop('case_insensitive', False)
        super().__init__(*args, case_insensitive=case_insensitive, **kwargs)
        self._ready_called = False
        self.daily_responders: Set[int] = set()
        self.user_scores: Dict[int, int] = {}
        self.user_tasks_created: Dict[int, List[Dict]] = {}
        self.task_counter = 0
        self.task_assignments: Dict[int, Dict[int, Dict]] = {}
        self.user_lives: Dict[int, int] = {}  # New: Track user lives
        self.help_command = None
        # Add to your bot class
        self.user_levels = {}  # user_id: level
        self.user_xp = {}      # user_id: xp

async def award_xp(self, user_id, amount):
    self.user_xp[user_id] = self.user_xp.get(user_id, 0) + amount
    xp_needed = 100 * (self.user_levels.get(user_id, 0) + 1)
    if self.user_xp[user_id] >= xp_needed:
        self.user_levels[user_id] = self.user_levels.get(user_id, 0) + 1
        await self.notify_level_up(user_id)

async def notify_level_up(self, user_id):
    user = await self.fetch_user(user_id)
    channel = self.get_channel(CHANNEL_ID)
    await channel.send(f"🎉 {user.mention} leveled up to level {self.user_levels[user_id]}!")



bot = TaskBot(command_prefix="!", intents=intents, case_insensitive=True)
bot.task_message_refs = {}  # user_id -> message object


def is_admin():

    def predicate(ctx):
        return ctx.author.id in ADMIN_ID

    return commands.check(predicate)


# ========== File Handling ==========
LOG_FILE = "daily_logs.json"
TASKS_FILE = "tasks.json"
COMMENTS_FILE = "comments.json"
# Add these constants near the top with other constants
BADGES_FILE = "badges.json"
WORK_SESSIONS_FILE = "work_sessions.json"
 
def with_parsed_date(param_name: str):
    """Decorator to parse a date parameter flexibly."""

    def decorator(func):

        @wraps(func)
        async def wrapper(ctx, *args, **kwargs):
            try:
                # Get the function signature
                sig = inspect.signature(func)

                # Bind the arguments
                bound_args = sig.bind(ctx, *args, **kwargs)
                bound_args.apply_defaults()

                # Get the parameter value
                if param_name in bound_args.arguments:
                    date_str = bound_args.arguments[param_name]
                    if date_str is not None:
                        # Parse the date
                        bound_args.arguments[param_name] = parse_flexible_date(
                            date_str)

                # Call the original function with parsed date
                return await func(*bound_args.args, **bound_args.kwargs)
            except ValueError as e:
                await ctx.send(f"❌ Invalid date: {str(e)}")
            except Exception as e:
                await ctx.send(f"❌ Error: {str(e)}")

        return wrapper

    return decorator


def parse_flexible_date(date_str: str, default_to_today: bool = False) -> str:
    """
    Parse date string flexibly, filling in current year if missing.
    Returns a date string in 'YYYY-MM-DD' format or raises ValueError.

    Args:
        date_str: The date string to parse (e.g., "25 May", "May 25", "today", "yesterday")
        default_to_today: If True and parsing fails, return today's date instead of raising error

    Returns:
        str: Date in 'YYYY-MM-DD' format
    """
    if not date_str and default_to_today:
        return datetime.now(EST).date().isoformat()

    date_str = date_str.strip().lower()

    # Handle special cases
    if date_str in ['today', 'now']:
        return datetime.now(EST).date().isoformat()
    if date_str == 'yesterday':
        return (datetime.now(EST) - timedelta(days=1)).date().isoformat()

    try:
        # Try parsing with dateutil first (handles most cases)
        dt = parser.parse(date_str, dayfirst=True, fuzzy=True)

        # If year is missing (defaults to 1900), replace with current year
        if dt.year == 1900:
            dt = dt.replace(year=datetime.now(EST).year)

        return dt.date().isoformat()
    except Exception:
        pass

    # Try manual parsing for common formats
    try:
        # Try 'DD MMM' format (e.g., "25 May")
        dt = datetime.strptime(date_str + f" {datetime.now(EST).year}",
                               "%d %b %Y")
        return dt.date().isoformat()
    except ValueError:
        pass

    try:
        # Try 'MMM DD' format (e.g., "May 25")
        dt = datetime.strptime(date_str + f" {datetime.now(EST).year}",
                               "%b %d %Y")
        return dt.date().isoformat()
    except ValueError:
        pass

    if default_to_today:
        return datetime.now(EST).date().isoformat()

    raise ValueError(f"Could not parse date: {date_str}")


async def cleanup_task_assignments():
    merged_assignments = {}

    # First pass - convert all keys to strings and merge duplicates
    for user_id, tasks in bot.task_assignments.items():
        str_id = str(user_id)
        if str_id not in merged_assignments:
            merged_assignments[str_id] = {}

        # Convert task IDs to strings if needed
        for task_id, task in tasks.items():
            merged_assignments[str_id][str(task_id)] = task

    # Second pass - verify user existence
    valid_assignments = {}
    for user_id, tasks in merged_assignments.items():
        try:
            user = await bot.fetch_user(int(user_id))
            valid_assignments[user_id] = tasks
        except discord.NotFound:
            continue

    bot.task_assignments = valid_assignments
    save_tasks(bot.task_assignments)


def award_points(user_id: str, task_id: str, points: int, description: str):
    try:
        with open("scores.json", "r") as f:
            scores = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        scores = {}

    if user_id not in scores:
        scores[user_id] = {}

    # Prevent duplicate point awards
    if task_id not in scores[user_id]:
        scores[user_id][task_id] = {
            "points": points,
            "description": description
        }

        with open("scores.json", "w") as f:
            json.dump(scores, f, indent=4)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(
            f"❌ Command not found. Use `!help` for available commands.",
            delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: {error.param.name}",
                       delete_after=10)
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Invalid argument: {str(error)}", delete_after=10)
    elif isinstance(error, commands.CheckFailure):
        pass  # Silent check failures are ignored
    else:
        error_embed = discord.Embed(
            title="❌ Command Error",
            description=f"An error occurred: {str(error)}",
            color=COLORS["error"])
        await ctx.send(embed=error_embed)
        # Log the error for debugging
        print(f"Error in command {ctx.command}: {error}", exc_info=True)


def save_created_tasks(data):
    with open("created_tasks.json", "w") as f:
        json.dump(data, f, indent=4)


def get_user_lives(user_id):
    lives = load_lives()
    return lives.get(str(user_id), 3)


def load_lives():
    try:
        with open("lives.json", "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_lives(lives_data):
    with open("lives.json", "w") as f:
        json.dump(lives_data, f, indent=2)


def load_logs():
    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)

        # Normalize all logs into list-of-dicts format
        for user_id in logs:
            for date in logs[user_id]:
                entry = logs[user_id][date]
                if isinstance(entry, str):
                    logs[user_id][date] = [{
                        "timestamp": "converted",
                        "log": entry
                    }]
                elif isinstance(entry, dict) and "log" in entry:
                    logs[user_id][date] = [entry]
                elif isinstance(entry, list):
                    new_entries = []
                    for e in entry:
                        if isinstance(e, str):
                            new_entries.append({
                                "timestamp": "converted",
                                "log": e
                            })
                        elif isinstance(e, dict):
                            new_entries.append(e)
                    logs[user_id][date] = new_entries

        return logs
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def migrate_logs():
    logs = load_logs()
    for user_id, user_logs in logs.items():
        for date, entry in user_logs.items():
            if isinstance(entry, dict):
                # Convert dictionary format to string
                log_text = entry.get('log', '')
                if isinstance(log_text, str) and log_text.startswith(
                        '"') and log_text.endswith('"'):
                    log_text = log_text[1:-1]
                logs[user_id][date] = log_text
            elif not isinstance(entry, str):
                logs[user_id][date] = str(entry)
    save_logs(logs)


def save_logs(logs: Dict[str, Dict[str, str]]):
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)


def load_tasks() -> Dict[str, Any]:
    try:
        with open(TASKS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_tasks(tasks: Dict[str, Any]):
    with open(TASKS_FILE, "w") as f:
        json.dump(tasks, f, indent=2)


def load_comments() -> Dict[str, List[Dict]]:
    try:
        with open(COMMENTS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_comments(comments: Dict[str, List[Dict]]):
    with open(COMMENTS_FILE, "w") as f:
        json.dump(comments, f, indent=2)


# ========== UI Components ==========
async def update_task_channel():
    channel = bot.get_channel(TASK_CHANNEL_ID)
    if not channel:
        print("❌ Task channel not found.")
        return

    for user_id, tasks in bot.task_assignments.items():
        if not tasks:
            continue

        # Delete old message for that user if exists
        old_message = bot.task_message_refs.get(user_id)
        if old_message:
            try:
                await old_message.delete()
            except discord.NotFound:
                pass  # Already deleted
            except Exception as e:
                print(f"Error deleting old message for user {user_id}: {e}")

        # Create new paginated view for this user
        view = TaskPaginatedView(tasks, user_id, label="All Tasks")
        embed = view.create_embed()
        try:
            new_message = await channel.send(embed=embed, view=view)
            bot.task_message_refs[user_id] = new_message
        except Exception as e:
            print(f"Error sending new task message for user {user_id}: {e}")


import discord
from discord.ui import View, button
from datetime import datetime

import discord
from discord.ui import View, button
from datetime import datetime, timezone


class TaskPaginatedView(discord.ui.View):
    STATUS_ICONS = {
        "Pending": "⏳",
        "Completed": "✅",
        "Overdue": "⚠️",
    }
    PRIORITY_EMOJIS = {"high": "🔥 High", "normal": "⭐ Normal", "low": "🛌 Low"}
    PRIORITY_COLORS = {
        "high": discord.Color.red(),
        "normal": discord.Color.gold(),
        "low": discord.Color.dark_grey()
    }

    def __init__(self, tasks: dict, user_id: int, label: str = "all"):
        super().__init__(timeout=None)  # No timeout, infinite lifetime
        self.tasks = list(tasks.items())  # list of (task_id, task_dict)
        self.user_id = user_id
        self.label = label
        self.current_page = 0

    @classmethod
    async def create_persistent_views(cls):
        # Register the persistent buttons
        bot.add_view(cls({}, 0))  # empty dict of tasks


# ✅ now gives both tasks and user_id

    def create_embed(self) -> discord.Embed:
        task_id, task = self.tasks[self.current_page]
        desc = task.get("description", "Untitled")
        status = task.get("status", "Pending")
        priority_raw = str(task.get("priority", "Normal")).lower()
        priority_display = self.PRIORITY_EMOJIS.get(priority_raw,
                                                    priority_raw.title())
        color = self.PRIORITY_COLORS.get(priority_raw, discord.Color.blue())
        importance = str(task.get("importance", "1")).title()

        # Determine status icon
        icon_label = self.STATUS_ICONS.get(status, "❔") + f" {status}"

        # Due date handling
        due_date_str = "No deadline"
        relative_due = None
        due_date = None
        if "due_date" in task and task["due_date"]:
            try:
                due_date = datetime.fromisoformat(task["due_date"])
                due_date_str = due_date.strftime("%b %d, %Y %H:%M")
                # Calculate relative due date
                now = datetime.now(
                    tz=due_date.tzinfo) if due_date.tzinfo else datetime.now()
                diff = due_date - now
                if diff.days >= 0:
                    relative_due = f"Due in {diff.days} day{'s' if diff.days != 1 else ''}"
                else:
                    relative_due = f"Overdue by {-diff.days} day{'s' if diff.days != -1 else ''}"
            except Exception:
                pass

        # User info
        user = None
        username = f"User ID {self.user_id}"
        try:
            # bot is a global variable; this assumes you have a global bot instance
            user = bot.get_user(self.user_id)
            if user:
                username = user.name
        except Exception:
            pass

        embed = discord.Embed(title=f"Task #{task_id} — {icon_label}",
                              description=f"**{desc}**",
                              color=color,
                              timestamp=datetime.utcnow())

        if user and user.avatar:
            embed.set_author(name=username, icon_url=user.avatar.url)
        else:
            embed.set_author(name=username)

        # Fields
        embed.add_field(name="Priority", value=priority_display, inline=True)
        embed.add_field(name="Importance", value=importance, inline=True)
        embed.add_field(name="Due Date", value=due_date_str, inline=True)

        if relative_due:
            embed.add_field(name="Due Date (Relative)",
                            value=relative_due,
                            inline=True)

        # Tags display (optional)
        tags = task.get("tags", [])
        if tags:
            tags_str = " ".join(f"`#{tag}`" for tag in tags)
            embed.add_field(name="Tags", value=tags_str, inline=False)

        # Progress bar (optional)
        progress = task.get("progress", None)
        if progress is not None:
            try:
                progress = int(progress)
                blocks = int(progress / 10)
                bar = "█" * blocks + "░" * (10 - blocks)
                embed.add_field(name="Progress",
                                value=f"{bar} {progress}%",
                                inline=False)
            except Exception:
                pass

        embed.set_footer(
            text=
            f"Task {self.current_page + 1} of {len(self.tasks)} | Filter: {self.label}"
        )

        return embed

    @button(label="◀️ Prev",
            style=discord.ButtonStyle.secondary,
            custom_id="task_prev")
    async def previous(self, interaction: discord.Interaction,
                       button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.create_embed(),
                                                    view=self)
        else:
            await interaction.response.defer()

    @button(label="Next ▶️",
            style=discord.ButtonStyle.secondary,
            custom_id="task_next")
    async def next(self, interaction: discord.Interaction,
                   button: discord.ui.Button):
        if self.current_page < len(self.tasks) - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.create_embed(),
                                                    view=self)
        else:
            await interaction.response.defer()
# Add these constants near the top with other constants
BADGES_FILE = "badges.json"
WORK_SESSIONS_FILE = "work_sessions.json"

# Add these classes near your other UI components
class BadgeCreationModal(discord.ui.Modal, title="Create New Badge"):
    def __init__(self, image_url=None):
        super().__init__()
        self.image_url = image_url

        self.add_item(discord.ui.TextInput(
            label="Badge Name",
            placeholder="Enter badge name...",
            required=True,
            max_length=50
        ))
        self.add_item(discord.ui.TextInput(
            label="Description",
            placeholder="What does this badge represent?",
            style=discord.TextStyle.long,
            required=True,
            max_length=200
        ))
        if not image_url:
            self.add_item(discord.ui.TextInput(
                label="Emoji/Image URL",
                placeholder="Enter emoji or image URL...",
                required=False
            ))
        self.add_item(discord.ui.TextInput(
            label="Points Reward",
            placeholder="Optional points to award (0 for none)",
            required=False,
            default="0"
        ))
        
    async def on_submit(self, interaction: discord.Interaction):
        try:
            badge_name = self.children[0].value
            description = self.children[1].value
            emoji_or_url = self.children[2].value.strip() or None
            points = int(self.children[3].value) if self.children[3].value.isdigit() else 0
            
            badges = load_badges()
            badge_id = str(len(badges) + 1)
            
            badges[badge_id] = {
                "name": badge_name,
                "description": description,
                "image": emoji_or_url,
                "points": points,
                "created_by": interaction.user.id,
                "created_at": datetime.now(EST).isoformat()
            }
            
            save_badges(badges)
            
            embed = discord.Embed(
                title="🛡️ New Badge Created",
                description=f"**{badge_name}** has been added to the badge collection!",
                color=COLORS["success"]
            )
            embed.add_field(name="Description", value=description, inline=False)
            if emoji_or_url:
                if emoji_or_url.startswith("http"):
                    embed.set_thumbnail(url=emoji_or_url)
                else:
                    embed.add_field(name="Emoji", value=emoji_or_url, inline=True)
            if points > 0:
                embed.add_field(name="Points Reward", value=str(points), inline=True)
                
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Error creating badge: {str(e)}",
                ephemeral=True
            )

# Add these helper functions
def load_badges():
    try:
        with open(BADGES_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_badges(badges):
    with open(BADGES_FILE, "w") as f:
        json.dump(badges, f, indent=4)

def load_work_sessions():
    try:
        with open(WORK_SESSIONS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_work_sessions(sessions):
    with open(WORK_SESSIONS_FILE, "w") as f:
        json.dump(sessions, f, indent=4)

def load_user_badges():
    try:
        with open("user_badges.json", "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_user_badges(user_badges):
    with open("user_badges.json", "w") as f:
        json.dump(user_badges, f, indent=4)

def award_badge(user_id: int, badge_id: str):
    badges = load_badges()
    user_badges = load_user_badges()
    
    if badge_id not in badges:
        return False
    
    if str(user_id) not in user_badges:
        user_badges[str(user_id)] = []
    
    if badge_id not in user_badges[str(user_id)]:
        user_badges[str(user_id)].append(badge_id)
        save_user_badges(user_badges)
        
        # Award points if badge has them
        if badges[badge_id].get("points", 0) > 0:
            award_points(str(user_id), f"badge_{badge_id}", 
                         badges[badge_id]["points"],
                         f"Earned badge: {badges[badge_id]['name']}")
        
        return True
    return False

@bot.command(name="createbadge", help="Create a new badge")
@is_admin()  # Your admin check here
async def createbadge(ctx):
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        # Ask for badge name
        await ctx.send("📝 What is the name of the badge?")
        name_msg = await bot.wait_for("message", timeout=60, check=check)
        badge_name = name_msg.content.strip()

        # Ask for description
        await ctx.send("💬 What's the description of the badge?")
        desc_msg = await bot.wait_for("message", timeout=60, check=check)
        description = desc_msg.content.strip()

        # Ask for emoji or image
        await ctx.send("📎 Upload an image or type an emoji. Type `skip` to skip.")
        image_msg = await bot.wait_for("message", timeout=60, check=check)
        if image_msg.attachments:
            image_url = image_msg.attachments[0].url
        elif image_msg.content.lower() == "skip":
            image_url = None
        else:
            image_url = image_msg.content.strip()

        # Ask for points
        await ctx.send("🎯 How many points should this badge give? Type a number or `0`.")
        points_msg = await bot.wait_for("message", timeout=60, check=check)
        points = int(points_msg.content.strip()) if points_msg.content.strip().isdigit() else 0

        # Build the badge embed
        embed = discord.Embed(
            title="🛡️ New Badge Created",
            description=f"**{badge_name}** has been added to the badge collection!",
            color=discord.Color.green()
        )
        embed.add_field(name="Description", value=description, inline=False)
        if image_url:
            if image_url.startswith("http"):
                embed.set_thumbnail(url=image_url)
            else:
                embed.add_field(name="Emoji", value=image_url, inline=True)
        if points > 0:
            embed.add_field(name="Points", value=str(points), inline=True)

        await ctx.send(embed=embed)

        # Save badge (you can adjust this)
        badges = load_badges()
        badge_id = str(len(badges) + 1)
        badges[badge_id] = {
            "name": badge_name,
            "description": description,
            "image": image_url,
            "points": points,
            "created_by": ctx.author.id,
            "created_at": datetime.now(EST).isoformat()
        }
        save_badges(badges)

    except asyncio.TimeoutError:
        await ctx.send("⏰ You took too long. Please try again.")



@bot.command(name="givebadge", help="Award a badge to a user (Admin only)")
@is_admin()
async def give_badge(ctx, member: discord.Member, badge_id: str):
    """Admin command to award a badge to a user"""
    badges = load_badges()
    if badge_id not in badges:
        return await ctx.send("❌ Badge ID not found.")
    
    if award_badge(member.id, badge_id):
        badge = badges[badge_id]
        embed = discord.Embed(
            title="🏆 Badge Awarded!",
            description=f"{member.mention} has earned the **{badge['name']}** badge!",
            color=COLORS["highlight"]
        )
        embed.add_field(name="Description", value=badge["description"], inline=False)
        if badge.get("image"):
            if badge["image"].startswith("http"):
                embed.set_thumbnail(url=badge["image"])
            else:
                embed.add_field(name="Emoji", value=badge["image"], inline=True)
        if badge.get("points", 0) > 0:
            embed.add_field(name="Points Awarded", value=str(badge["points"]), inline=True)
            
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ User already has this badge.")

@bot.command(name="badges", help="List all available badges")
async def list_badges(ctx):
    """List all badges in the system"""
    badges = load_badges()
    if not badges:
        return await ctx.send("ℹ️ No badges have been created yet.")
    
    embed = discord.Embed(
        title="🛡️ Available Badges",
        description="Here are all the badges you can earn:",
        color=COLORS["primary"]
    )
    
    for badge_id, badge in badges.items():
        value = badge["description"]
        if badge.get("points", 0) > 0:
            value += f"\n🔹 Reward: {badge['points']} points"
        embed.add_field(
            name=f"{badge_id}. {badge['name']}",
            value=value,
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name="startwork", help="Start a work session to earn points")
async def start_work(ctx):
    """Start tracking a work session"""
    sessions = load_work_sessions()
    user_id = str(ctx.author.id)
    
    if user_id in sessions and "start_time" in sessions[user_id]:
        return await ctx.send("❌ You already have an active work session!")
    
    sessions[user_id] = {
        "start_time": datetime.now(EST).isoformat(),
        "proof_message_id": ctx.message.id,
        "proof_channel_id": ctx.channel.id
    }
    save_work_sessions(sessions)
    
    embed = discord.Embed(
        title="⏱️ Work Session Started",
        description="Your work session has begun! Use `!endwork` when you're done to earn points.",
        color=COLORS["success"]
    )
    embed.set_footer(text="You'll need to provide proof of work when ending the session")
    await ctx.send(embed=embed)

@bot.command(name="endwork", help="End your work session and earn points")
async def end_work(ctx, proof: Optional[str] = None):
    """End a work session and earn points"""
    sessions = load_work_sessions()
    user_id = str(ctx.author.id)
    
    if user_id not in sessions or "start_time" not in sessions[user_id]:
        return await ctx.send("❌ You don't have an active work session!")
    
    if not proof:
        # Check if they attached any files
        if not ctx.message.attachments:
            return await ctx.send("❌ Please provide proof of your work (text description or file attachment)")
    
    start_time = datetime.fromisoformat(sessions[user_id]["start_time"])
    end_time = datetime.now(EST)
    duration = end_time - start_time
    minutes = int(duration.total_seconds() / 60)
    points = int(minutes * 0.5)  # 0.5 points per minute
    
    if points < 1:
        points = 1  # Minimum 1 point
    
    # Verify proof if required
    proof_text = ""
    if proof:
        proof_text = proof
    elif ctx.message.attachments:
        proof_text = " ".join([att.url for att in ctx.message.attachments])
    else:
        proof_text = "No proof provided"
    
    # Award points
    session_id = f"work_{start_time.strftime('%Y%m%d_%H%M%S')}"
    award_points(user_id, session_id, points, f"Work session: {minutes} minutes")
    
    # Save session details
    sessions[user_id]["end_time"] = end_time.isoformat()
    sessions[user_id]["duration_minutes"] = minutes
    sessions[user_id]["points_earned"] = points
    sessions[user_id]["proof"] = proof_text
    save_work_sessions(sessions)
    
    # Check for badge eligibility
    badges_earned = []
    badges = load_badges()
    
    # Check for marathon badge (long session)
    if minutes >= 120:  # 2+ hour session
        for badge_id, badge in badges.items():
            if "marathon" in badge["name"].lower():
                if award_badge(ctx.author.id, badge_id):
                    badges_earned.append(badge["name"])
    
    # Check for frequent worker badge (multiple sessions)
    user_sessions = [s for s in sessions.values() if s.get("user_id") == user_id]
    if len(user_sessions) >= 5:  # 5+ sessions
        for badge_id, badge in badges.items():
            if "dedicated" in badge["name"].lower():
                if award_badge(ctx.author.id, badge_id):
                    badges_earned.append(badge["name"])
    
    # Prepare response
    embed = discord.Embed(
        title="✅ Work Session Completed",
        description=f"You worked for {minutes} minutes and earned {points} points!",
        color=COLORS["success"]
    )
    embed.add_field(name="Proof Submitted", value=proof_text[:1000], inline=False)
    
    if badges_earned:
        embed.add_field(
            name="🏆 New Badges Earned!",
            value="\n".join(badges_earned),
            inline=False
        )
    
    await ctx.send(embed=embed)
    await update_leaderboard_channel()
    
    # Clear the session
    del sessions[user_id]
    save_work_sessions(sessions)

# Update the profile command to show badges
from discord.ui import View, Button

class BadgeListView(View):
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.badges = load_user_badges().get(str(user_id), [])
        self.all_badges = load_badges()

        if len(self.badges) > 0:
            self.add_item(Button(label="View All Badges", style=discord.ButtonStyle.primary, custom_id=f"view_badges_{user_id}"))

@bot.command(name="profile", help="View your profile and stats")
async def user_profile(ctx, member: discord.Member = None):
    member = member or ctx.author

    if member != ctx.author and ctx.author.id != ADMIN_ID:
        return await ctx.send(embed=create_error_embed("Permission Denied", "You can only view your own profile unless you're an admin"))

    logs = load_logs()
    user_logs = logs.get(str(member.id), {})
    user_badges = load_user_badges().get(str(member.id), [])
    badges = load_badges()

    embed = discord.Embed(
        title=f"👤 {member.display_name}'s Profile",
        color=COLORS["primary"],
        timestamp=datetime.now(EST)
    )

    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)

    embed.add_field(name="Member Since", value=member.joined_at.strftime("%B %d, %Y"), inline=True)
    embed.add_field(name="Log Entries", value=f"{len(user_logs)} this week", inline=True)

    assigned_tasks = len(bot.task_assignments.get(member.id, {}))
    completed_tasks = sum(
        1 for task in bot.task_assignments.get(member.id, {}).values()
        if task.get("status") == "Completed"
    )
    embed.add_field(
        name="Tasks",
        value=f"Assigned: {assigned_tasks}\nCompleted: {completed_tasks}",
        inline=True
    )

    if user_badges:
        badge_list = []
        for badge_id in user_badges[:5]:  # Show first 5 badges
            if badge_id in badges:
                badge = badges[badge_id]
                display = (badge.get("image") or "🛡️") + " " + badge["name"]
                badge_list.append(display)

        badge_text = "\n".join(badge_list)
        if len(user_badges) > 5:
            badge_text += f"\n...and {len(user_badges)-5} more"

        embed.add_field(
            name=f"Badges ({len(user_badges)})",
            value=badge_text,
            inline=False
        )
        await ctx.send(embed=embed, view=BadgeListView(member.id))
    else:
        embed.add_field(
            name="Badges",
            value="No badges yet. Complete tasks to earn some!",
            inline=False
        )
        await ctx.send(embed=embed)


@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.data.get("custom_id", "").startswith("view_badges_"):
        user_id = interaction.data["custom_id"].split("_")[-1]
        user_badges = load_user_badges().get(user_id, [])
        all_badges = load_badges()

        if not user_badges:
            await interaction.response.send_message("No badges to display!", ephemeral=True)
            return

        pages = []
        for badge_id in user_badges:
            if badge_id in all_badges:
                badge = all_badges[badge_id]
                embed = discord.Embed(
                    title=f"🏅 Badge: {badge['name']}",
                    description=badge.get("description", ""),
                    color=COLORS["primary"]
                )
                embed.add_field(name="Badge ID", value=badge_id)
                if badge["image"].startswith("http"):
                    embed.set_thumbnail(url=badge["image"])
                else:
                    embed.add_field(name="Emoji", value=badge["image"])
                embed.add_field(name="Points", value=str(badge.get("points", 0)))
                pages.append(embed)

        class Paginator(View):
            def __init__(self, pages):
                super().__init__(timeout=120)
                self.pages = pages
                self.index = 0

            @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
            async def previous(self, interaction, button):
                self.index = (self.index - 1) % len(self.pages)
                await interaction.response.edit_message(embed=self.pages[self.index], view=self)

            @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
            async def next(self, interaction, button):
                self.index = (self.index + 1) % len(self.pages)
                await interaction.response.edit_message(embed=self.pages[self.index], view=self)

        await interaction.response.send_message(embed=pages[0], view=Paginator(pages), ephemeral=True)




from discord.ui import Button, View

class ViewBadgesButton(Button):
    def __init__(self, user_badges, all_badges):
        super().__init__(label="🔍 View All Badges", style=discord.ButtonStyle.primary)
        self.user_badges = user_badges
        self.all_badges = all_badges

    async def callback(self, interaction: discord.Interaction):
        if not self.user_badges:
            return await interaction.response.send_message("❌ No badges to show.", ephemeral=True)

        embed = self.create_badge_embed(0)
        view = BadgePagination(self.user_badges, self.all_badges, 0)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    def create_badge_embed(self, index):
        badge_id = self.user_badges[index]
        badge = self.all_badges.get(badge_id, {})

        embed = discord.Embed(
            title=f"🏅 {badge.get('name', 'Unknown Badge')}",
            description=badge.get("description", 'No description.'),
            color=COLORS["secondary"]
        )

        image_url = badge.get("image", "")
        if image_url.startswith("http"):
            embed.set_thumbnail(url=image_url)
        elif image_url:
            embed.description = f"{image_url} {embed.description}"

        embed.set_footer(text=f"Badge {index + 1} of {len(self.user_badges)}")
        return embed


class BadgePagination(View):
    def __init__(self, user_badges, all_badges, index):
        super().__init__(timeout=60)
        self.user_badges = user_badges
        self.all_badges = all_badges
        self.index = index

        self.add_item(Button(label="⬅️ Previous", style=discord.ButtonStyle.secondary, disabled=index == 0))
        self.add_item(Button(label="➡️ Next", style=discord.ButtonStyle.secondary, disabled=index == len(user_badges) - 1))

        self.children[0].callback = self.prev_page
        self.children[1].callback = self.next_page

    def get_embed(self, index):
        badge_id = self.user_badges[index]
        badge = self.all_badges.get(badge_id, {})

        embed = discord.Embed(
            title=f"🏅 {badge.get('name', 'Unknown Badge')}",
            description=badge.get("description", 'No description.'),
            color=COLORS["secondary"]
        )

        image_url = badge.get("image", "")
        if image_url.startswith("http"):
            embed.set_thumbnail(url=image_url)
        elif image_url:
            embed.description = f"{image_url} {embed.description}"

        embed.set_footer(text=f"Badge {index + 1} of {len(self.user_badges)}")
        return embed

    async def prev_page(self, interaction: discord.Interaction):
        self.index -= 1
        embed = self.get_embed(self.index)
        await interaction.response.edit_message(embed=embed, view=BadgePagination(self.user_badges, self.all_badges, self.index))

    async def next_page(self, interaction: discord.Interaction):
        self.index += 1
        embed = self.get_embed(self.index)
        await interaction.response.edit_message(embed=embed, view=BadgePagination(self.user_badges, self.all_badges, self.index))


class TaskCreationModal(discord.ui.Modal, title="Create New Task"):

    def __init__(self):
        super().__init__()
        self.add_item(
            discord.ui.TextInput(label="Task Name",
                                 placeholder="Enter task name...",
                                 required=True,
                                 max_length=100))
        self.add_item(
            discord.ui.TextInput(label="Description",
                                 placeholder="Enter detailed description...",
                                 style=discord.TextStyle.long,
                                 required=True,
                                 max_length=500))
        self.add_item(
            discord.ui.TextInput(label="Due Date & Time (YYYY-MM-DD HH:MM)",
                                 placeholder="Leave blank for no due date",
                                 required=False))
        self.add_item(
            discord.ui.TextInput(label="Priority and Importance (e.g. high|4)",
                                 placeholder="normal|3",
                                 required=False))
        self.add_item(
            discord.ui.TextInput(label="Points",
                                 placeholder="10",
                                 required=False))

    async def on_submit(self, interaction: discord.Interaction):
        name = self.children[0].value
        description = f"{name}: {self.children[1].value}"
        due_datetime_str = self.children[2].value.strip()

        priority_importance_str = self.children[3].value.strip() or "normal|3"
        points_str = self.children[4].value.strip() or "10"

        # Parse priority and importance
        if '|' in priority_importance_str:
            priority_part, importance_part = priority_importance_str.split(
                '|', 1)
        else:
            priority_part = priority_importance_str
            importance_part = "3"  # default importance

        priority = priority_part.strip().lower()
        valid_priorities = ["very low", "low", "normal", "high", "very high"]
        if priority not in valid_priorities:
            priority = "normal"

        try:
            importance = int(importance_part.strip())
            if not 1 <= importance <= 5:
                importance = 3
        except ValueError:
            importance = 3

        try:
            points = int(points_str)
        except ValueError:
            points = 10

        due_datetime = None
        if due_datetime_str:
            try:
                due_datetime = EST.localize(
                    datetime.strptime(due_datetime_str, "%Y-%m-%d %H:%M"))
            except ValueError:
                await interaction.response.send_message(
                    "❌ Invalid date & time format! Please use YYYY-MM-DD HH:MM (24-hour format).",
                    ephemeral=True)
                return

        bot.task_counter += 1
        task_id = bot.task_counter
        task_info = {
            "name": name,
            "description": description,
            "due_date": due_datetime.isoformat() if due_datetime else None,
            "priority": priority,
            "importance": importance,  # stored separately
            "points": points,
            "created_at": datetime.now(EST).isoformat(),
            "status": "Pending"
        }

        bot.user_tasks_created.setdefault(interaction.user.id,
                                          {})[task_id] = task_info

        embed = discord.Embed(title=f"📝 Task #{task_id} Added",
                              color=COLORS["success"])
        embed.add_field(name="Name", value=name, inline=False)
        embed.add_field(name="Description", value=description, inline=False)
        embed.add_field(name="Due Date/Time",
                        value=due_datetime.strftime("%Y-%m-%d %H:%M")
                        if due_datetime else "Not specified",
                        inline=True)
        embed.add_field(name="Priority", value=priority.title(), inline=True)
        embed.add_field(name="Importance", value=str(importance), inline=True)
        embed.add_field(name="Points", value=str(points), inline=True)
        embed.set_footer(text=f"Created by {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)


class LogsPaginatedView(discord.ui.View):

    def __init__(self, member: discord.Member, logs: list, page: int = 0):
        super().__init__(timeout=60)
        self.member = member
        self.logs = logs  # List of (date, entry) tuples
        self.page = page
        self.logs_per_page = 5  # Show 5 logs per page

    def create_embed(self):
        embed = discord.Embed(title=f"📚 Logs for {self.member.display_name}",
                              color=COLORS["primary"])

        # Paginate logs
        start_idx = self.page * self.logs_per_page
        end_idx = start_idx + self.logs_per_page
        page_logs = self.logs[start_idx:end_idx]

        for date, entry in page_logs:
            embed.add_field(name=f"📅 {date}", value=entry, inline=False)

        total_pages = (len(self.logs) // self.logs_per_page) + 1
        embed.set_footer(text=f"Page {self.page + 1}/{total_pages}")

        return embed

    @discord.ui.button(label="◄", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction,
                            button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            embed = self.create_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="►", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction,
                        button: discord.ui.Button):
        if (self.page + 1) * self.logs_per_page < len(self.logs):
            self.page += 1
            embed = self.create_embed()
            await interaction.response.edit_message(embed=embed, view=self)


class LeaderboardView(discord.ui.View):

    def __init__(self, leaderboard_data: List[tuple]):
        super().__init__(timeout=None)
        self.leaderboard_data = leaderboard_data  # (rank, user_id, total, tasks)
        self.current_page = 0

    @classmethod
    async def create_persistent_views(cls):
        bot.add_view(cls([]))  # empty dict instead of list

    @discord.ui.button(label="◄",
                       style=discord.ButtonStyle.secondary,
                       custom_id="leaderboard:prev")
    async def previous_page(self, interaction: discord.Interaction,
                            button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.create_embed(),
                                                    view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="►",
                       style=discord.ButtonStyle.secondary,
                       custom_id="leaderboard:next")
    async def next_page(self, interaction: discord.Interaction,
                        button: discord.ui.Button):
        if self.current_page < len(self.leaderboard_data) - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.create_embed(),
                                                    view=self)
        else:
            await interaction.response.defer()

    def create_embed(self) -> discord.Embed:
        rank, user_id, total, tasks = self.leaderboard_data[self.current_page]
        user = bot.get_user(user_id)
        display_name = user.display_name if user else f"User {user_id}"
        avatar_url = user.display_avatar.url if user else discord.Embed.Empty

        embed = discord.Embed(title=f"🏅 Leaderboard — Rank #{rank}",
                              color=COLORS["highlight"])

        embed.add_field(name="👤 User",
                        value=f"**{display_name}** (`{user_id}`)",
                        inline=False)
        embed.add_field(name="⭐ Total Points",
                        value=f"`{total}` pts",
                        inline=False)

        if tasks:
            task_lines = "\n".join(
                f"• `{task.get('description', tid)}` — **{task['points']} pts**"
                for tid, task in tasks.items())
        else:
            task_lines = "*No completed tasks yet.*"

        embed.add_field(name="📋 Completed Tasks",
                        value=task_lines,
                        inline=False)
        embed.set_footer(
            text=f"Page {self.current_page + 1} / {len(self.leaderboard_data)}"
        )
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        return embed


# 1. Update HealthLogsView to properly handle logging
class HealthLogsView(discord.ui.View):

    def __init__(self, user_id: int, logs: Dict[str, List[Dict]]):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.logs = sorted([(date, entries) for date, entries in logs.items()],
                           key=lambda x: x[0],
                           reverse=True)
        self.current_page = 0
        self.logs_per_page = 1

    async def on_timeout(self):
        # Disable buttons when view times out
        for item in self.children:
            item.disabled = True

    def create_embed(self) -> discord.Embed:
        member = bot.get_user(self.user_id)
        embed = discord.Embed(
            title=
            f"📊 Work Logs for {member.display_name if member else 'Unknown User'}",
            color=COLORS["primary"],
            timestamp=datetime.now(EST))

        if self.logs:
            current_date, entries = self.logs[self.current_page]
            try:
                date_obj = datetime.strptime(current_date, "%Y-%m-%d").date()
                formatted_date = date_obj.strftime("%A, %B %d, %Y")
            except ValueError:
                formatted_date = current_date

            embed.description = f"📅 **{formatted_date}**\n"

            for entry in entries:
                if isinstance(entry, dict):
                    log_text = entry.get("log", "")
                    timestamp = entry.get("timestamp", "")
                    embed.description += f"\n```\n{log_text}\n```\n"
                else:
                    embed.description += f"\n```\n{entry}\n```\n"

        footer_date = date_obj.strftime('%m/%d/%Y')
        now = datetime.now().strftime('%I:%M %p')
        embed.set_footer(
            text=
            f"Page {self.current_page + 1}/{len(self.logs)} • {footer_date} • Today at {now}",
            icon_url="https://i.imgur.com/7W0MJXP.png")

        return embed

    @discord.ui.button(label="◄ Previous", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction,
                            button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.create_embed(),
                                                    view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Next ►", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction,
                        button: discord.ui.Button):
        if self.current_page < len(self.logs) - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.create_embed(),
                                                    view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="📝 Log Work",
                       style=discord.ButtonStyle.primary,
                       emoji="✏️")
    async def log_work_button(self, interaction: discord.Interaction,
                              button: discord.ui.Button):
        # Send the log modal
        await interaction.response.send_modal(LogModal())


class LogButton(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)  # persistent view

    @discord.ui.button(
        label="Log My Work",
        style=discord.ButtonStyle.primary,
        custom_id="persistent_log_button"  # Required for persistence
    )
    async def log_button(self, interaction: discord.Interaction,
                         button: discord.ui.Button):
        await interaction.response.send_modal(LogModal())


class SingleLogPaginatedView(View):

    def __init__(self, user, entries):
        super().__init__(timeout=60)
        self.user = user
        self.entries = entries
        self.index = 0

        self.prev_button = Button(label="⬅️ Previous",
                                  style=discord.ButtonStyle.secondary)
        self.next_button = Button(label="Next ➡️",
                                  style=discord.ButtonStyle.secondary)
        self.prev_button.callback = self.go_previous
        self.next_button.callback = self.go_next
        self.add_item(self.prev_button)
        self.add_item(self.next_button)

    def create_embed(self):
        entry = self.entries[self.index]
        embed = discord.Embed(
            title=f"📄 Log Entry {self.index + 1} of {len(self.entries)}",
            color=discord.Color.blue())
        embed.add_field(name="User ID", value=self.user.id, inline=False)
        embed.add_field(name="Date", value=entry["date"], inline=True)
        embed.add_field(name="Log", value=entry["log"], inline=False)
        return embed

    async def go_previous(self, interaction: discord.Interaction):
        if self.index > 0:
            self.index -= 1
            await interaction.response.edit_message(embed=self.create_embed(),
                                                    view=self)

    async def go_next(self, interaction: discord.Interaction):
        if self.index < len(self.entries) - 1:
            self.index += 1
            await interaction.response.edit_message(embed=self.create_embed(),
                                                    view=self)


class LogModal(discord.ui.Modal, title="Log Your Work"):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_item(
            discord.ui.TextInput(label="What did you work on?",
                                 placeholder="Describe your work here...",
                                 style=discord.TextStyle.long,
                                 required=True,
                                 max_length=1000))

    async def on_submit(self, interaction: discord.Interaction):
        today = datetime.now(EST).date().isoformat()
        log_entry = self.clean_input(self.children[0].value)
        user_id = str(interaction.user.id)

        logs = load_logs()

        if user_id not in logs:
            logs[user_id] = {}

        if today not in logs[user_id]:
            logs[user_id][today] = []

        # Normalize if old data
        if isinstance(logs[user_id][today], str):
            logs[user_id][today] = [{
                "timestamp": "converted",
                "log": logs[user_id][today]
            }]
        elif isinstance(logs[user_id][today], dict):
            logs[user_id][today] = [logs[user_id][today]]

        logs[user_id][today].append({
            "timestamp": datetime.now(EST).isoformat(),
            "log": log_entry
        })

        save_logs(logs)

        await interaction.response.send_message(embed=discord.Embed(
            title="✅ Log Saved",
            description="Your log has been saved!",
            color=COLORS["success"]),
                                                ephemeral=True)

    def clean_input(self, text: str) -> str:
        """Clean and sanitize input text"""
        # Remove excessive whitespace
        cleaned = ' '.join(text.strip().split())
        # Basic profanity filter could be added here
        return cleaned


class HelpView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(
            discord.ui.Button(label="Need More Help?",
                              url="https://discord.gg/your-support-server"))

    @discord.ui.button(label="Close Help", style=discord.ButtonStyle.danger)
    async def close_help(self, interaction: discord.Interaction,
                         button: discord.ui.Button):
        await interaction.message.delete()


# ========== Helper functions ==========
def format_task(task: Dict[str, Any], task_id: int) -> str:
    desc = task.get("description", "No description")
    due = task.get("due_date", None)
    due_str = f" | Due: {due}" if due else ""
    priority = task.get("priority", "Normal")
    status = task.get("status", "Pending")
    assigned_by = task.get("assigned_by_name", "Unknown")
    return f"ID: {task_id} | {desc} | Priority: {priority} | Status: {status}{due_str} | Assigned by: {assigned_by}"


def parse_due_date(date_str: Optional[str]) -> Optional[str]:
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        if dt < datetime.now(EST).date():
            return None
        return dt.isoformat()
    except ValueError:
        return None


def priority_from_str(p: Optional[str]) -> str:
    p = (p or "normal").lower()
    if p in ["low", "medium", "high"]:
        return p.capitalize()
    return "Normal"


def create_success_embed(title: str, description: str) -> discord.Embed:
    return discord.Embed(title=f"✅ {title}",
                         description=description,
                         color=COLORS["success"])


def create_error_embed(title: str, description: str) -> discord.Embed:
    return discord.Embed(title=f"❌ {title}",
                         description=description,
                         color=COLORS["error"])


def create_info_embed(title: str, description: str) -> discord.Embed:
    return discord.Embed(title=f"ℹ️ {title}",
                         description=description,
                         color=COLORS["primary"])


async def update_leaderboard_channel():
    leaderboard_channel_id = 1376588983059873933  # Replace with your actual channel ID
    channel = bot.get_channel(leaderboard_channel_id)

    if channel is None:
        print(
            f"❌ Could not find leaderboard channel with ID {leaderboard_channel_id}"
        )
        return

    # 🧹 Clear existing leaderboard messages
    async for msg in channel.history(limit=10):
        if msg.author == bot.user and (msg.embeds
                                       or "Congratulations" in msg.content):
            await msg.delete()

    # 📥 Load scores
    try:
        with open("scores.json", "r") as f:
            scores = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        scores = {}

    # 📊 Prepare leaderboard data with total scores
    leaderboard_data = []
    for user_id, tasks in scores.items():
        total = sum(task.get("points", 0) for task in tasks.values())
        leaderboard_data.append((int(user_id), total, tasks))

    if not leaderboard_data:
        embed = discord.Embed(title="🏆 Leaderboard",
                              description="No scores yet!",
                              color=COLORS["highlight"])
        await channel.send(embed=embed)
        return

    # 🔽 Sort and assign ranks with tie handling
    leaderboard_data.sort(key=lambda x: x[1], reverse=True)

    ranked_leaderboard = []
    last_score = None
    rank = 0
    skip = 1
    for i, (user_id, total, tasks) in enumerate(leaderboard_data):
        if total != last_score:
            rank += skip
            skip = 1
        else:
            skip += 1
        last_score = total
        ranked_leaderboard.append((rank, user_id, total, tasks))

    # 📤 Create and send paginated leaderboard view
    view = LeaderboardView(ranked_leaderboard)
    embed = view.create_embed()
    await channel.send(embed=embed, view=view)

    # 🎉 Congratulate all Top 1 users
    top1_users = [uid for r, uid, _, _ in ranked_leaderboard if r == 1]
    mentions = []
    for uid in top1_users:
        user = await bot.fetch_user(uid)
        mentions.append(f"**{user.display_name}**")
    await channel.send(
        f"🎉 Congratulations to {', '.join(mentions)} for being **Top 1** on the leaderboard!"
    )


# 3. Update LogModal to award points
class LogModal(discord.ui.Modal, title="Log Your Work"):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_item(
            discord.ui.TextInput(label="What did you work on?",
                                 placeholder="Describe your work here...",
                                 style=discord.TextStyle.long,
                                 required=True,
                                 max_length=1000))

    async def on_submit(self, interaction: discord.Interaction):
        today = datetime.now(EST).date().isoformat()
        log_entry = self.children[0].value
        user_id = str(interaction.user.id)

        logs = load_logs()

        if user_id not in logs:
            logs[user_id] = {}

        if today not in logs[user_id]:
            logs[user_id][today] = []

        # Normalize if old data
        if isinstance(logs[user_id][today], str):
            logs[user_id][today] = [{
                "timestamp": "converted",
                "log": logs[user_id][today]
            }]
        elif isinstance(logs[user_id][today], dict):
            logs[user_id][today] = [logs[user_id][today]]

        logs[user_id][today].append({
            "timestamp": datetime.now(EST).isoformat(),
            "log": log_entry
        })

        save_logs(logs)

        # Award 2 points for daily logging
        award_points(user_id, f"daily_log_{today}", 2,
                     f"Completed log for {today}")

        # Update leaderboard
        await update_leaderboard_channel()

        await interaction.response.send_message(embed=discord.Embed(
            title="✅ Log Saved (+2 points)",
            description="Your log has been saved and you earned 2 points!",
            color=COLORS["success"]),
                                                ephemeral=True)


# ========== Scheduled Tasks ==========
@tasks.loop(minutes=1)
async def daily_log_reminder():
    now_est = datetime.now(EST)

    # Check if it's 6:00 PM EST
    if now_est.hour == 14 and now_est.minute == 00:
        channel = bot.get_channel(CHANNEL_ID)
        if channel is None:
            return

        today = str(now_est.date())
        user_logs = load_logs()
        guild = channel.guild
        members = [m for m in guild.members if not m.bot]

        slackers = [
            m.mention for m in members
            if str(m.id) not in user_logs or today not in user_logs[str(m.id)]
        ]

        if slackers:
            embed = discord.Embed(
                title="🔔 Daily Log Reminder",
                description=
                f"These users haven't logged yet: {', '.join(slackers)}",
                color=COLORS["warning"])
            embed.add_field(
                name="How to Log",
                value=
                "Click the button below or use `!log` to log your work. And remember, who ever doesn't log, he's getting touched by me 😈",
                inline=False)
            embed.set_thumbnail(url="https://i.imgur.com/7W0MJXP.png")
            await channel.send(embed=embed, view=LogButton())


@tasks.loop(minutes=1)
async def send_summary_to_admin():
    await bot.wait_until_ready()
    now_est = datetime.now(EST)
    if now_est.time().hour == 0 and now_est.time().minute == 0:
        logs = load_logs()
        admin = bot.get_user(ADMIN_ID)
        if admin is None:
            return

        if not logs:
            embed = discord.Embed(title="📊 Daily Summary",
                                  description="No logs recorded today",
                                  color=COLORS["info"])
            await admin.send(embed=embed)
            return

        for user_id, user_logs in logs.items():
            user = bot.get_user(int(user_id))
            if not user:
                continue

            embed = discord.Embed(title=f"📝 Daily Logs - {user.display_name}",
                                  color=COLORS["primary"],
                                  timestamp=now_est)

            today = datetime.now(EST).date().isoformat()
            if today in user_logs:
                entries = user_logs[today]
                if isinstance(entries, str):
                    entries = [{"log": entries}]
                elif isinstance(entries, dict):
                    entries = [entries]

                log_text = ""
                for entry in entries:
                    if isinstance(entry, dict):
                        timestamp = entry.get("timestamp", "")
                        log = entry.get("log", "")
                        log_text += f"**{timestamp}**\n{log}\n\n"
                    else:
                        log_text += f"{entry}\n\n"

                if log_text:
                    embed.add_field(name=f"📅 {today}",
                                    value=log_text,
                                    inline=False)

                embed.set_footer(text="End of summary")
                await admin.send(embed=embed)


@tasks.loop(minutes=60)  # Runs every hour
async def evening_ping_task():
    now = datetime.now(EST)
    current_time = now.time()
    today = now.date()

    # Only run between 4 PM and 11:59 PM
    if not (time(16, 0) <= current_time <= time(23, 59, 59)):
        return

    channel = bot.get_channel(CHANNEL_ID)
    user_logs = load_logs()
    members = [m for m in channel.guild.members if not m.bot]

    slackers = [
        m.mention for m in members
        if str(m.id) not in user_logs or str(today) not in user_logs[str(m.id)]
    ]

    if slackers:
        await channel.send(embed=discord.Embed(
            title="⚠️ Reminder: Log Your Work",
            description=
            f"These users haven't logged today: {', '.join(slackers)}. Log in now or I'm coming to touch you'll.",
            color=COLORS["warning"]))


@tasks.loop(hours=1)
async def check_overdue_tasks():
    await bot.wait_until_ready()
    tasks_data = load_tasks()
    now = datetime.now(EST).date()
    channel = bot.get_channel(TASK_CHANNEL_ID)
    if channel is None:
        return

    for member_id_str, member_tasks in tasks_data.items():
        for task_id_str, task in member_tasks.items():
            if task.get("status") != "Completed" and task.get("due_date"):
                due_date = datetime.fromisoformat(task["due_date"]).date()

                if due_date < now:
                    member = channel.guild.get_member(int(member_id_str))
                    if member:
                        embed = discord.Embed(
                            title="⚠️ Overdue Task",
                            description=
                            f"You have an overdue task:\n{format_task(task, int(task_id_str))}",
                            color=COLORS["error"])
                        try:
                            await member.send(embed=embed)
                        except:
                            pass


@tasks.loop(hours=24)
async def daily_reset_responders():
    bot.daily_responders.clear()


@daily_reset_responders.before_loop
async def before_reset():
    now = datetime.now(EST)
    next_midnight = datetime.combine(now + timedelta(days=1), time(0, 0))
    wait_seconds = (next_midnight - now).total_seconds()
    await asyncio.sleep(wait_seconds)


# ========== Events ==========
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    await bot.process_commands(message)


class SilentCheckFailure(commands.CheckFailure):
    """Special exception that gets silently ignored"""
    pass


def admin_only():

    async def predicate(ctx):
        if ctx.author.id != ADMIN_ID:
            try:
                await ctx.message.delete()
            except discord.Forbidden:
                pass
            raise SilentCheckFailure()  # This will be silently caught
        return True

    return commands.check(predicate)


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')

    GUILD_ID = 1353179636896632832  # Replace this with your server's ID
    guild = discord.Object(id=GUILD_ID)
    await bot.tree.sync(guild=guild)
    
    # --- Load Data ---
    try:
        with open("scores.json", "r") as f:
            bot.user_scores = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        bot.user_scores = {}

    migrate_logs()  # Legacy migration (if needed)
    bot.user_lives = load_lives()
    bot.add_view(LogButton())  # Persistent buttons
    await TaskPaginatedView.create_persistent_views()
    await LeaderboardView.create_persistent_views()  # Dummy data

    # --- Task Initialization ---
    bot.task_assignments = load_tasks()
    bot.user_tasks_created = {}
    bot.comments = load_comments()

    # Debug: Print loaded tasks to verify due dates
    print(
        f"\n[Task Debug] Loaded {len(bot.task_assignments)} users with tasks:")
    for user_id, tasks in bot.task_assignments.items():
        print(f"  User {user_id}: {len(tasks)} tasks")
        for task_id, task in tasks.items():
            if "due_date" in task:
                print(f"    Task {task_id} → Due: {task['due_date']}")

    # Set task counter
    if bot.task_assignments:
        bot.task_counter = max(
            max(map(int, user_tasks.keys()))
            for user_tasks in bot.task_assignments.values() if user_tasks)

    # --- START LOOPS FIRST (to prevent missing reminders) ---
    background_tasks = [
        daily_log_reminder,
        send_summary_to_admin,
        evening_ping_task,
        check_overdue_tasks,
        daily_reset_responders,
        check_due_dates,  # MOST CRITICAL FOR REMINDERS
        weekly_summary
    ]

    for task in background_tasks:
        if not task.is_running():
            task.start()
            print(f"Started loop: {task}"
                  )  # if you just want to confirm it started

    # --- THEN Cleanup/Update ---
    await cleanup_task_assignments()
    await update_task_channel()

    # --- Normalize Task Storage ---
    print("\nNormalizing task storage...")
    bot.task_assignments = {
        str(user_id): tasks
        for user_id, tasks in bot.task_assignments.items()
    }
    save_tasks(bot.task_assignments)
    print(f"Normalized {len(bot.task_assignments)} users' tasks")

    print("\nBot fully initialized! ✅")


@bot.event
async def on_raw_reaction_add(payload):
    if payload.emoji.name != "✅":
        return
    if payload.channel_id != CHANNEL_ID:
        return

    user = bot.get_user(payload.user_id)
    if user is None or user.bot:
        return

    user_logs = load_logs()
    today = str(datetime.now(EST).date())
    user_id_str = str(user.id)

    if user_id_str not in user_logs:
        user_logs[user_id_str] = {}
    user_logs[user_id_str][today] = "✅ Quick log via reaction"
    save_logs(user_logs)

    embed = create_success_embed("Quick Log",
                                 "Your quick log has been recorded! Thanks!")
    try:
        await user.send(embed=embed)
    except:
        pass


@bot.command(name="myscore", help="View your total score and task breakdown")
async def myscore(ctx):
    user_id = str(ctx.author.id)
    if not hasattr(bot, 'user_scores') or user_id not in bot.user_scores:
        return await ctx.send("❌ You have no recorded tasks or points.")

    tasks = bot.user_scores[user_id]
    total_points = sum(task["points"] for task in tasks.values())
    breakdown = "\n".join(
        f"• {task['description'] or task_id}: {task['points']} pts"
        for task_id, task in tasks.items())

    embed = discord.Embed(
        title=f"📊 Score Report for {ctx.author.display_name}",
        description=f"**Total Points:** {total_points}\n\n{breakdown}",
        color=COLORS["info"])
    await ctx.send(embed=embed)


@bot.command(name="help")
async def custom_help(ctx, command_name: str = None):
    # Define admin commands (these will be hidden from regular users)
    admin_commands = {
        "assign": {
            "description": "Assign a task to a member",
            "syntax": "!assign @member <task_id>"
        },
        "forcework": {
            "description": "Ping everyone who hasn't logged work today",
            "syntax": "!forcework"
        },
        "alllogs": {
            "description": "View all users' logs",
            "syntax": "!alllogs"
        },
        "forework": {
            "description": "Ping users who haven't logged today",
            "syntax": "!forework"
        },
        "backup": {
            "description": "Create a backup of all data",
            "syntax": "!backup"
        },
        "alltasks": {
            "description": "View all tasks in the system",
            "syntax": "!alltasks"
        },
        "resetlogs": {
            "description": "Reset logs for a user or date",
            "syntax": "!resetlogs [@user] [date]"
        },
        "adjustpoints": {
            "description": "Adjust user points",
            "syntax": "!adjustpoints @member add/remove <amount>"
        },
        "addlife": {
            "description": "Add a life to a user",
            "syntax": "!addlife @member"
        },
        "removelife": {
            "description": "Remove a life from a user",
            "syntax": "!removelife @member"
        },
        "removetask": {
            "description": "Remove tasks from users",
            "syntax": "!removetask [@user] [task_id]"
        },
        "adminlog": {
            "description": "Add a log entry for a user with optional date",
            "syntax": "!adminlog @user [date] <message>"
        },
        "testreminder": {
            "description": "Test task reminder system",
            "syntax": "!testreminder <task_id>"
        }
    }

    # Define regular commands
    regular_commands = {
        "log": {
            "description": "Log your daily work",
            "syntax": "!log <message>"
        },
        "viewlogs": {
            "description": "View your logs",
            "syntax": "!viewlogs [@user]"
        },
        "editlog": {
            "description": "Edit your last log",
            "syntax": "!editlog <date> <new_message>"
        },
        "health": {
            "description": "View your logs in a beautiful format",
            "syntax": "!health [@user]"
        },
        "exportlogs": {
            "description": "Export your logs as a file",
            "syntax": "!exportlogs"
        },
        "createtask": {
            "description": "Create a new task (form)",
            "syntax": "!createtask"
        },
        "addtask": {
            "description": "Add a new task (command)",
            "syntax": "!addtask \"description\" [due_date] [priority] [points]"
        },
        "mytasks": {
            "description": "View your assigned tasks",
            "syntax": "!mytasks"
        },
        "completetask": {
            "description": "Mark a task as completed",
            "syntax": "!completetask <task_id>"
        },
        "tasks": {
            "description":
            "View your tasks with filtering options",
            "syntax":
            "!tasks [filter] [sort]\nFilters: pending, completed, overdue\nSort: due, priority"
        },
        "myscore": {
            "description": "View your current score and points breakdown",
            "syntax": "!myscore"
        },
        "updatetask": {
            "description":
            "Update a task's description, due date/time, priority, and points.",
            "syntax":
            "!updatetask <task_id> \"new description\" [today|tomorrow|YYYY-MM-DD] [HH:MM] [low|normal|high] [points]",
        },
        "commenttask": {
            "description": "Add comment to a task",
            "syntax": "!commenttask <task_id> <comment>"
        },
        "viewcomments": {
            "description": "View comments on a task",
            "syntax": "!viewcomments <task_id>"
        },
        "searchtasks": {
            "description": "Search your tasks",
            "syntax": "!searchtasks <keyword>"
        },
        "addcategory": {
            "description": "Add a category to task",
            "syntax": "!addcategory <task_id> <category>"
        },
        "taskchart": {
            "description": "View tasks by priority",
            "syntax": "!taskchart"
        },
        "leaderboard": {
            "description": "Show top contributors",
            "syntax": "!leaderboard"
        },
        "profile": {
            "description": "View your profile",
            "syntax": "!profile [@user]"
        },
        "checklives": {
            "description": "Check your remaining lives",
            "syntax": "!checklives [@user]"
        },
        "snooze": {
            "description": "Snooze reminders",
            "syntax": "!snooze <minutes>"
        },
        "tasks": {
            "description":
            "View assigned tasks for yourself or another user.",
            "syntax":
            "!tasks - View your tasks\n!tasks @user - View tasks assigned to that user\n!tasks @user [filter] - Filter tasks by status (overdue, completed, pending)\nExample: !tasks @Muhammad pending"
        },
        "myscore": {
            "description": "View your total score and task breakdown",
            "syntax": "!myscore"
        }
    }

    if command_name:
        # Handle specific command help
        cmd_name = command_name.lower()

        # Check if it's an admin command first
        if cmd_name in admin_commands:
            if ctx.author.id in ADMIN_ID:
                # Delete the admin's message
                try:
                    await ctx.message.delete()
                except discord.Forbidden:
                    pass

                # Send help to DMs
                cmd_info = admin_commands[cmd_name]
                embed = discord.Embed(title=f"Admin Help: {cmd_name}",
                                      description=cmd_info["description"],
                                      color=COLORS["primary"])
                embed.add_field(name="Syntax",
                                value=f"`{cmd_info['syntax']}`",
                                inline=False)

                try:
                    await ctx.author.send(embed=embed)
                except discord.Forbidden:
                    await ctx.send(
                        "⚠️ Couldn't DM you the help. Please enable DMs.",
                        delete_after=10)
                return
            else:
                # Non-admin trying to access admin command
                await ctx.send("❌ Command not found", delete_after=5)
            return

        # Handle regular command help
        if cmd_name in regular_commands:
            cmd_info = regular_commands[cmd_name]
            embed = discord.Embed(title=f"Help: {cmd_name}",
                                  description=cmd_info["description"],
                                  color=COLORS["primary"])
            embed.add_field(name="Syntax",
                            value=f"`{cmd_info['syntax']}`",
                            inline=False)
            await ctx.send(embed=embed)
            return
        else:
            await ctx.send("❌ Command not found", delete_after=5)
            return

    # No command specified - show general help
    embed = discord.Embed(title="📚 TaskBot Help",
                          description="Use `!help <command>` for more info",
                          color=COLORS["primary"])

    # Add regular commands
    embed.add_field(
        name="📝 Logging Commands",
        value="\n".join([
            f"`{cmd}`"
            for cmd in ["log", "viewlogs", "editlog", "health", "exportlogs"]
        ]),
        inline=False)

    embed.add_field(name="📋 Task Commands",
                    value="\n".join([
                        f"`{cmd}`" for cmd in [
                            "createtask",
                            "addtask",
                            "mytasks",
                            "updatetask",
                            "commenttask",
                            "viewcomments",
                            "searchtasks",
                            "addcategory",
                            "taskchart",
                            "tasks",
                            "completetask",
                        ]
                    ]),
                    inline=False)

    embed.add_field(
        name="🏆 Profile Commands",
        value="\n".join([
            f"`{cmd}`"
            for cmd in ["leaderboard", "profile", "checklives", "myscore"]
        ]),
        inline=False)

    await ctx.send(embed=embed)

    # If admin, send admin commands in DM
    if ctx.author.id in ADMIN_ID:
        admin_embed = discord.Embed(
            title="⚙️ Admin Commands",
            description="These commands are only available to you",
            color=COLORS["primary"])
        admin_embed.add_field(
            name="Admin Tools",
            value="\n".join([f"`{cmd}`" for cmd in admin_commands.keys()]),
            inline=False)
        try:
            await ctx.author.send(embed=admin_embed)
        except discord.Forbidden:
            await ctx.send("⚠️ Couldn't DM you admin commands",
                           delete_after=10)


@bot.command(name="progress")
async def show_progress(ctx):
    xp = bot.user_xp.get(ctx.author.id, 0)
    level = bot.user_levels.get(ctx.author.id, 0)
    xp_needed = 100 * (level + 1)
    progress = int((xp / xp_needed) * 20)
    
    bar = "[" + "█" * progress + "░" * (20 - progress) + "]"
    embed = discord.Embed(title=f"{ctx.author.display_name}'s Progress",
                         description=f"Level {level}\n{bar} {xp}/{xp_needed} XP",
                         color=COLORS["primary"])
    await ctx.send(embed=embed)


weekly_challenges = {
    "task_master": {
        "goal": 5,
        "reward": 50,
        "desc": "Complete 5 tasks this week"
    },
    "log_king": {
        "goal": 7,
        "reward": 70,
        "desc": "Log work 7 days in a row"
    }
}

@bot.command(name="challenges")
async def show_challenges(ctx):
    embed = discord.Embed(title="Weekly Challenges", color=COLORS["highlight"])
    for name, challenge in weekly_challenges.items():
        embed.add_field(name=challenge["desc"],
                       value=f"Reward: {challenge['reward']} XP",
                       inline=False)
    await ctx.send(embed=embed)

@bot.command(name="tasks", help="Show your tasks (admins can check others)")
@commands.guild_only()
async def show_user_tasks(ctx, member: discord.Member = None, *args):
    # Determine user (same logic as you have)
    target_member = ctx.author
    filter_arg = None
    sort_arg = None
    filter_options = {"pending", "completed", "overdue", "all"}
    sort_options = {"due", "priority"}

    if member and isinstance(member, discord.Member):
        if not is_admin()(ctx) and member != ctx.author:
            await ctx.send("❌ Only admins can view other users' tasks!",
                           delete_after=10)
            return
        target_member = member
        if args:
            filter_arg = args[0].lower()
        if len(args) > 1:
            sort_arg = args[1].lower()
    else:
        if isinstance(member, str):
            args = (member, ) + args
        if args:
            filter_arg = args[0].lower()
        if len(args) > 1:
            sort_arg = args[1].lower()

    if filter_arg not in filter_options and filter_arg is not None:
        await ctx.send(
            "❌ Invalid filter! Use: pending, completed, overdue, or all.",
            delete_after=10)
        return

    if sort_arg not in sort_options and sort_arg is not None:
        await ctx.send("❌ Invalid sort! Use: due or priority.",
                       delete_after=10)
        return

    user_id = target_member.id
    if user_id not in bot.task_assignments or not bot.task_assignments[user_id]:
        await ctx.send(f"{target_member.mention} has no tasks.")
        return

    now = datetime.now(EST)

    # Collect filtered tasks in dict format {task_id: task}
    filtered_tasks = {}

    for task_id, task in bot.task_assignments[user_id].items():
        status = task.get("status", "Pending")
        due_date = None
        if "due_date" in task and task["due_date"]:
            try:
                due_date = datetime.fromisoformat(
                    task["due_date"]).astimezone(EST)
            except ValueError:
                due_date = None

        # Apply filter_arg
        if filter_arg in (None, "all"):
            add_task = True
        elif filter_arg == "pending" and status == "Pending" and (
                not due_date or due_date >= now):
            add_task = True
        elif filter_arg == "completed" and status == "Completed":
            add_task = True
        elif filter_arg == "overdue" and status != "Completed" and due_date and due_date < now:
            add_task = True
        else:
            add_task = False

        if add_task:
            filtered_tasks[task_id] = task

    if not filtered_tasks:
        await ctx.send(
            f"{target_member.mention} has no tasks matching that filter.")
        return

    # Sort filtered tasks by your sort_arg
    def sort_key_due(item):
        tid, t = item
        due = None
        if "due_date" in t and t["due_date"]:
            try:
                due = datetime.fromisoformat(t["due_date"]).astimezone(EST)
            except ValueError:
                pass
        return due or datetime.max

    def sort_key_priority(item):
        tid, t = item
        priority_order = {"high": 0, "normal": 1, "low": 2}
        return priority_order.get(t.get("priority", "normal").lower(), 1)

    items = list(filtered_tasks.items())
    if sort_arg == "due":
        items.sort(key=sort_key_due)
    elif sort_arg == "priority":
        items.sort(key=sort_key_priority)

    sorted_tasks = dict(items)

    # Create paginated view — assuming your TaskPaginatedView accepts a dict of tasks, user_id, and a label
    view = TaskPaginatedView(sorted_tasks, user_id, label=filter_arg or "all")
    embed = view.create_embed()

    await ctx.send(embed=embed, view=view)


@bot.command(name="viewlogs",
             help="View your logs or another user's logs (admin only)")
async def view_logs(ctx, member: discord.Member = None):
    """View logs for yourself or another user (admin only)"""
    target_member = member or ctx.author

    # Permission check
    if target_member != ctx.author and ctx.author.id != ADMIN_ID:
        embed = discord.Embed(
            title="⛔ Access Denied",
            description=
            "You can only view your own logs unless you're an admin",
            color=COLORS["error"])
        return await ctx.send(embed=embed, delete_after=10)

    logs = load_logs()
    user_logs = logs.get(str(target_member.id), {})

    if not user_logs:
        embed = discord.Embed(
            title="📭 No Logs Found",
            description=
            f"{target_member.display_name} hasn't logged anything yet!",
            color=COLORS["warning"])
        return await ctx.send(embed=embed, view=LogButton())

    # Create paginated view
    view = HealthLogsView(target_member.id, user_logs)
    embed = view.create_embed()
    await ctx.send(embed=embed, view=view)


@bot.command(name="testreminder")
@is_admin()
async def testreminder(ctx, task_id: int):
    """Force a reminder for testing"""
    task = None
    for user_tasks in bot.task_assignments.values():
        if task_id in user_tasks:
            task = user_tasks[task_id]
            break

    if not task:
        return await ctx.send("Task not found")

    # Force a reminder
    embed = discord.Embed(
        title="🔔 TEST REMINDER",
        description=f"Test reminder for task {task_id}: {task['description']}",
        color=COLORS["info"])
    await ctx.send(embed=embed)


@bot.command(name="leaderboard")
async def leaderboard(ctx):
    try:
        with open("scores.json", "r") as f:
            scores = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return await ctx.send("❌ No scores available yet.")

    leaderboard_data = []
    for user_id, tasks in scores.items():
        total = sum(task.get("points", 0) for task in tasks.values())
        leaderboard_data.append((int(user_id), total, tasks))

    if not leaderboard_data:
        return await ctx.send("❌ No participants yet.")

    leaderboard_data.sort(key=lambda x: x[1], reverse=True)
    view = LeaderboardView(leaderboard_data)
    embed = view.create_embed()
    await ctx.send(embed=embed, view=view)


@bot.command(name="adjustpoints",
             help="Add or remove points from a user (Admin only)")
@is_admin()
async def adjust_points(ctx, member: discord.Member, action: str, amount: int,
                        *, rest: str):
    import shlex
    action = action.lower()

    if action not in ["add", "remove"]:
        return await ctx.send("❌ Invalid action. Use `add` or `remove`.")

    if amount <= 0:
        return await ctx.send("❌ Amount must be a positive number.")

    try:
        args = shlex.split(rest)
    except Exception:
        return await ctx.send(
            "❌ Invalid format. Use quotes properly.\n"
            "**Example:** `!adjustpoints @User add 10 \"task42\" \"Write docs\"` or `!adjustpoints @User add 10 \"Write docs\"`"
        )

    # Load scores
    try:
        with open("scores.json", "r") as f:
            scores = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        scores = {}

    user_id_str = str(member.id)
    if user_id_str not in scores:
        scores[user_id_str] = {}

    user_tasks = scores[user_id_str]

    task_id = None
    description = ""
    note = ""

    if action == "add":
        if len(args) == 1:
            # Only description provided, generate task ID
            description = args[0]
            base_id = "task"
            index = 1
            while f"{base_id}{index}" in user_tasks:
                index += 1
            task_id = f"{base_id}{index}"
        elif len(args) >= 2:
            task_id = args[0]
            description = args[1]
        if len(args) >= 3:
            note = args[2]
    else:  # remove
        # Try by ID
        if args[0] in user_tasks:
            task_id = args[0]
            description = user_tasks[task_id].get("description", "")
        else:
            # Try by matching description
            for tid, task in user_tasks.items():
                if task.get("description", "") == args[0]:
                    task_id = tid
                    description = task.get("description", "")
                    break
            if not task_id:
                return await ctx.send(
                    f"❌ No task found with ID or description `{args[0]}` for {member.mention}"
                )
        if len(args) >= 2:
            note = args[1]

    current_task = user_tasks.get(task_id, {
        "points": 0,
        "description": description,
        "notes": []
    })
    current_points = current_task.get("points", 0)

    new_points = max(
        0, current_points + amount if action == "add" else current_points -
        amount)
    action_word = "added to" if action == "add" else "removed from"

    # Append note if present
    if note:
        current_task.setdefault("notes", []).append(note)

    # Update description (only when adding)
    if action == "add":
        current_task["description"] = description

    # Save or delete task
    if new_points == 0:
        user_tasks.pop(task_id, None)
    else:
        current_task["points"] = new_points
        user_tasks[task_id] = current_task

    # Save to file
    with open("scores.json", "w") as f:
        json.dump(scores, f, indent=2)

    # Update cache if using
    if hasattr(bot, 'user_scores'):
        if new_points == 0:
            if user_id_str in bot.user_scores:
                bot.user_scores[user_id_str].pop(task_id, None)
                if not bot.user_scores[user_id_str]:
                    bot.user_scores.pop(user_id_str, None)
        else:
            if user_id_str not in bot.user_scores:
                bot.user_scores[user_id_str] = {}
            bot.user_scores[user_id_str][task_id] = current_task

    total_points = sum(task["points"] for task in user_tasks.values())

    # Respond
    embed = discord.Embed(
        title="✅ Points Adjusted",
        description=
        f"{amount} points {action_word} {member.mention} for task `{description}`",
        color=COLORS["success"])
    embed.add_field(name="New Task Score", value=f"{new_points} points")
    embed.add_field(name="Total Score", value=f"{total_points} points")
    footer = f"Adjusted by {ctx.author.display_name}"
    if note:
        footer += f" | Note: {note}"
    embed.set_footer(text=footer)

    await ctx.send(embed=embed)
    await update_leaderboard_channel()


@bot.command(name="forcework",
             help="Ping everyone who hasn't logged work today (Admin only)")
@admin_only()
@commands.has_permissions(administrator=True)
async def forcework(ctx):
    # Load all logs
    logs = load_logs()
    today = str(datetime.now(EST).date())

    # Get all member IDs who have logged today
    logged_today = set()
    for user_id, dates in logs.items():
        if today in dates and dates[today]:
            logged_today.add(user_id)

    # Get all members in the guild (server)
    guild = ctx.guild
    if guild is None:
        await ctx.send("⚠️ This command can only be run in a server.")
        return

    # Find members who have not logged today
    not_logged_members = []
    for member in guild.members:
        if member.bot:
            continue  # skip bots
        if str(member.id) not in logged_today:
            not_logged_members.append(member)

    if not not_logged_members:
        await ctx.send("✅ Everyone has logged work today!")
    else:
        # Build mention string
        mentions = " ".join(member.mention for member in not_logged_members)
        await ctx.send(
            f"⚠️ The following users have NOT logged work today:\n{mentions}. Please log your work or else i'm coming to touch you kids 😈"
        )

    # Delete the command message to keep chat clean
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass  # Bot lacks permission to delete message


@bot.command(name='touch')
async def touch_member(ctx, member: discord.Member):
    """Playfully 'touch' a member with a custom message (Admin only)"""
    # More direct "I'm coming" style messages
    touch_messages = [
        f"I'm coming for you, {member.mention}! Better get ready! 😈",
        f"Lock your doors, {member.mention}... I'm on my way! 👀",
        f"3... 2... 1... I'm touching {member.mention} RIGHT NOW! 💀",
        f"Hope you're wearing clean underwear, {member.mention}, because I'M COMING! 👻",
        f"*evil laugh* {member.mention}, you can run but you can't hide! 🏃‍♂️💨",
        f"Alert! Alert! {member.mention}, my hands are approaching your general direction! 🚨",
        f"Initiate panic sequence! {member.mention}, I'm deploying the touch! ⚠️",
        f"Brace yourself, {member.mention}... the touch is inevitable! 👐",
        f"Warning: {member.mention}, I'm within touching distance! 🔔",
        f"Final warning, {member.mention}... retreat now or face the touch! ⏳",
        f"Too late to escape, {member.mention}! The touch is already happening! 👋",
        f"Mission: Touch {member.mention} - Status: IN PROGRESS 🎯",
        f"*ominous footsteps* I'm getting closer, {member.mention}... 👣",
        f"Activating touch protocol on {member.mention}! No survivors! ☠️",
        f"RED ALERT! {member.mention}, I'm about to violate your personal space! 🚩"
    ]
    message = random.choice(touch_messages)

    embed = discord.Embed(description=message, color=0xFF0000)
    await ctx.send(embed=embed)
    # Try to delete the original command message
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="alllogs",
             help="View all users' logs with pagination (Admin only)")
@admin_only()
async def alllogs(ctx):
    """Admin command to view all logs in a paginated format"""
    logs = load_logs()
    guild = ctx.guild
    if guild is None:
        await ctx.send("⚠️ This command can only be used in a server.")
        return

    # Delete the command message
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass

    if not logs:
        await ctx.author.send("📭 No logs found.")
        return

    # Create a list of (user_id, user_logs) tuples sorted by most recent log date
    sorted_users = sorted([(uid, user_logs)
                           for uid, user_logs in logs.items()],
                          key=lambda x: max(x[1].keys()) if x[1] else "",
                          reverse=True)

    # Create paginated view
    view = AllLogsPaginatedView(ctx.author, sorted_users, guild)
    embed = view.create_embed()
    await ctx.author.send(embed=embed, view=view)


class AllLogsPaginatedView(discord.ui.View):

    def __init__(self, requester: discord.Member, user_logs: List[tuple],
                 guild: discord.Guild):
        super().__init__(timeout=None)
        self.requester = requester
        self.user_logs = user_logs
        self.guild = guild
        self.current_page = 0
        self.current_log_page = 0
        self.logs_per_page = 3
        self.message = None  # To be set later

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass

    def create_embed(self) -> discord.Embed:
        user_id, logs = self.user_logs[self.current_page]
        member = self.guild.get_member(int(user_id))
        display_name = member.display_name if member else f"User ID {user_id}"

        embed = discord.Embed(title=f"📚 Logs for {display_name}",
                              color=COLORS["primary"],
                              timestamp=datetime.now(EST))

        sorted_dates = sorted(logs.items(), key=lambda x: x[0], reverse=True)
        total_pages = (len(sorted_dates) + self.logs_per_page -
                       1) // self.logs_per_page

        start = self.current_log_page * self.logs_per_page
        end = start + self.logs_per_page
        paged_dates = sorted_dates[start:end]

        for date, entries in paged_dates:
            try:
                date_obj = datetime.strptime(date, "%Y-%m-%d").date()
                formatted_date = date_obj.strftime("%A, %B %d, %Y")
            except ValueError:
                formatted_date = date

            if isinstance(entries, str):
                entries = [{"log": entries}]
            elif isinstance(entries, dict):
                entries = [entries]

            log_text = ""
            for entry in entries:
                if isinstance(entry, dict):
                    timestamp = entry.get("timestamp", "")
                    log = entry.get("log", "")
                    log_text += f"**{timestamp}**\n{log}\n\n"
                else:
                    log_text += f"{entry}\n\n"

            embed.add_field(name=f"📅 {formatted_date}",
                            value=log_text or "No log content",
                            inline=False)

        embed.set_footer(text=(
            f"User ID: {user_id} • User Page {self.current_page + 1}/{len(self.user_logs)} • "
            f"Log Page {self.current_log_page + 1}/{total_pages}"))
        return embed

    @discord.ui.button(label="⬅ Logs", style=discord.ButtonStyle.secondary)
    async def previous_logs(self, interaction: discord.Interaction,
                            button: discord.ui.Button):
        if self.current_log_page > 0:
            self.current_log_page -= 1
            await interaction.response.edit_message(embed=self.create_embed(),
                                                    view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Logs ➡", style=discord.ButtonStyle.secondary)
    async def next_logs(self, interaction: discord.Interaction,
                        button: discord.ui.Button):
        _, logs = self.user_logs[self.current_page]
        total_pages = (len(logs) + self.logs_per_page -
                       1) // self.logs_per_page
        if self.current_log_page < total_pages - 1:
            self.current_log_page += 1
            await interaction.response.edit_message(embed=self.create_embed(),
                                                    view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="◄ Previous User",
                       style=discord.ButtonStyle.secondary)
    async def previous_user(self, interaction: discord.Interaction,
                            button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.current_log_page = 0
            await interaction.response.edit_message(embed=self.create_embed(),
                                                    view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Next User ►",
                       style=discord.ButtonStyle.secondary)
    async def next_user(self, interaction: discord.Interaction,
                        button: discord.ui.Button):
        if self.current_page < len(self.user_logs) - 1:
            self.current_page += 1
            self.current_log_page = 0
            await interaction.response.edit_message(embed=self.create_embed(),
                                                    view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Jump to User", style=discord.ButtonStyle.primary)
    async def jump_to_user(self, interaction: discord.Interaction,
                           button: discord.ui.Button):
        options = []
        for i, (user_id, _) in enumerate(self.user_logs):
            member = self.guild.get_member(int(user_id))
            label = member.display_name if member else f"User {user_id}"
            options.append(
                discord.SelectOption(label=label[:25],
                                     value=str(i),
                                     description=f"View {label}'s logs"))

        select = discord.ui.Select(placeholder="Select a user...",
                                   options=options[:25])

        async def select_callback(interaction: discord.Interaction):
            self.current_page = int(select.values[0])
            self.current_log_page = 0
            await interaction.response.edit_message(embed=self.create_embed(),
                                                    view=self)

        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message(
            "Select a user to view their logs:", view=view, ephemeral=True)

    @discord.ui.button(label="📅 Jump to Date",
                       style=discord.ButtonStyle.primary)
    async def jump_to_date(self, interaction: discord.Interaction,
                           button: discord.ui.Button):
        try:
            _, logs = self.user_logs[self.current_page]
            sorted_dates = sorted(logs.items(),
                                  key=lambda x: x[0],
                                  reverse=True)

            date_to_page = {
                date: idx // self.logs_per_page
                for idx, (date, _) in enumerate(sorted_dates)
            }

            options = []
            for date, page in date_to_page.items():
                try:
                    date_obj = datetime.strptime(date, "%Y-%m-%d").date()
                    label = date_obj.strftime("%b %d, %Y")
                except ValueError:
                    label = date
                options.append(
                    discord.SelectOption(
                        label=label[:100],
                        value=f"{page}:{date}",  # ✅ Make value unique
                        description=f"Jump to logs from {label}"[:100]))

            select = discord.ui.Select(placeholder="Select a date...",
                                       options=options[:25])

            async def select_callback(select_interaction: discord.Interaction):
                page_str = select.values[0].split(":")[0]
                self.current_log_page = int(page_str)
                await select_interaction.response.edit_message(
                    embed=self.create_embed(), view=self)

            select.callback = select_callback

            view = discord.ui.View()
            view.add_item(select)

            await interaction.response.send_message(
                content="📅 Select a date to jump to:",
                view=view,
                ephemeral=True)

        except Exception as e:
            print(f"⚠️ Error in jump_to_date: {e}")
            await interaction.response.send_message(
                "An error occurred while preparing date options.",
                ephemeral=True)


@bot.command(name="editlog", help="Edit your last log from a specific date")
async def edit_log(ctx, date: str, *, new_desc: str):
    user_logs = load_logs()
    user_id = str(ctx.author.id)

    # Parse date using natural language
    parsed_date = dateparser.parse(date)
    if not parsed_date:
        return await ctx.send(
            "❌ Couldn't understand the date you gave. Try `today`, `yesterday`, or `2025-05-25`."
        )

    date_str = str(parsed_date.date())

    if user_id not in user_logs or date_str not in user_logs[user_id]:
        return await ctx.send(f"❌ No logs found for `{date_str}`.")

    if not user_logs[user_id][date_str]:
        return await ctx.send("❌ No logs to edit on that date.")

    # Edit the last log entry for that date
    user_logs[user_id][date_str][-1]["log"] = new_desc
    user_logs[user_id][date_str][-1]["timestamp"] = datetime.now(
        EST).isoformat()
    save_logs(user_logs)

    await ctx.send(f"✅ Updated your last log on `{date_str}` to:\n`{new_desc}`"
                   )

    # Delete user message for cleanliness
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="snooze",
             help="Snooze your daily log reminder for X minutes")
async def snooze(ctx, minutes: int):
    if minutes < 1 or minutes > 180:
        embed = create_error_embed(
            "Invalid Input",
            "Please provide a snooze time between 1 and 180 minutes.")
        return await ctx.send(embed=embed)

    daily_log_reminder.cancel()
    embed = create_info_embed("Snooze Active",
                              f"Reminders snoozed for {minutes} minutes.")
    await ctx.send(embed=embed)

    await asyncio.sleep(minutes * 60)
    daily_log_reminder.start()

    embed = create_info_embed("Reminders Active",
                              "Daily reminders are now active again.")
    await ctx.send(embed=embed)
    await ctx.message.delete()


@bot.command(name="addtask")
async def add_task(ctx, *, args=None):
    """Add a new task with standard date format (YYYY-MM-DD), optional priority, and points"""
    if not args:
        embed = create_error_embed(
            "Invalid Format",
            "Usage: `!addtask \"description\" [due_date] [priority] [points]`\n"
            "• Date must be in format `YYYY-MM-DD`\n"
            "• Priority can be `low`, `normal`, or `high`\n"
            "• Points is a number (default 10)")
        return await ctx.send(embed=embed)

    import shlex
    try:
        tokens = shlex.split(args)
    except ValueError:
        return await ctx.send(
            "❌ Error parsing arguments. Use quotes around your task description."
        )

    if not tokens:
        return await ctx.send("❌ Task description is missing.")

    description = tokens[0]
    remaining = tokens[1:]

    due_date = None
    priority = "normal"
    points = 10  # Default points

    for token in remaining:
        if token.lower() in {"low", "normal", "high"}:
            priority = token.lower()
        elif token.isdigit():
            points = int(token)
        else:
            try:
                due_date = datetime.strptime(token, "%Y-%m-%d")
            except ValueError:
                return await ctx.send(
                    "❌ Invalid date format! Use `YYYY-MM-DD`.")

    bot.task_counter += 1
    task_id = bot.task_counter
    task_info = {
        "description": description,
        "due_date": due_date.isoformat() if due_date else None,
        "priority": priority,
        "points": points,  # Add points to task
        "created_at": str(datetime.now(EST)),
    }

    bot.user_tasks_created.setdefault(ctx.author.id, {})[task_id] = task_info

    embed = discord.Embed(title=f"📝 Task #{task_id} Added",
                          color=COLORS["success"])
    embed.add_field(name="Description", value=description, inline=False)
    embed.add_field(
        name="Due Date",
        value=due_date.strftime("%Y-%m-%d") if due_date else "Not specified",
        inline=True)
    embed.add_field(name="Priority", value=priority.capitalize(), inline=True)
    embed.add_field(name="Points", value=str(points), inline=True)
    embed.set_footer(text=f"Created by {ctx.author.display_name}")

    await ctx.send(embed=embed)
    await update_task_channel()  # Update task channel


@bot.command(name="assign", help="Assign task to member")
@is_admin()
async def assign_task(ctx, member: discord.Member, task_id: int):
    try:
        # Find the task without deleting it from the creator's list
        task_found = None
        for creator_id, tasks in bot.user_tasks_created.items():
            if task_id in tasks:
                task_found = tasks[task_id]
                break  # Do not delete the original task

        if not task_found:
            return await ctx.send("❌ Task not found.")

        if task_id in bot.task_assignments.get(member.id, {}):
            return await ctx.send(
                "⚠️ This task is already assigned to that user.")

        # Add to assignee's task list
        if member.id not in bot.task_assignments:
            bot.task_assignments[member.id] = {}

        bot.task_assignments[member.id][task_id] = {
            **task_found, "status": "Pending",
            "assigned_at": datetime.now(EST).isoformat(),
            "assigned_by": ctx.author.id
        }

        save_tasks(bot.task_assignments)
        await ctx.send(f"✅ Task #{task_id} assigned to {member.mention}")
        await update_task_channel()

    except Exception as e:
        await ctx.send(f"❌ Error assigning task: {e}")


@bot.command(name="completetask", help="Mark a task as completed")
async def complete_task(ctx, task_id: int):
    user_tasks = bot.task_assignments.get(ctx.author.id, {})
    if task_id not in user_tasks:
        return await ctx.send("❌ Task not found in your assignments.")

    task = user_tasks[task_id]
    if task.get("status") == "Completed":
        return await ctx.send("❌ Task already completed.")

    task["status"] = "Completed"
    task["completed_at"] = datetime.now(EST).isoformat()
    points = task.get("points", 10)

    # Award points
    award_points(str(ctx.author.id), str(task_id), points,
                 task.get("description", f"Task #{task_id}"))

    # Update leaderboard
    await update_leaderboard_channel()
    await update_task_channel()

    await ctx.send(f"✅ Task #{task_id} marked as completed! +{points} points")


@bot.command(name="createtask", help="Create a new task using a form")
async def create_task(ctx):
    """Create a task using a pop-up form"""
    # Create a view with a button that will trigger the modal
    view = discord.ui.View()

    # Add a button that will show the modal when clicked
    button = discord.ui.Button(label="Create Task",
                               style=discord.ButtonStyle.primary)

    async def button_callback(interaction):
        await interaction.response.send_modal(TaskCreationModal())

    button.callback = button_callback
    view.add_item(button)

    await ctx.send("Click the button below to create a new task:", view=view)


# ========== New Life System Commands ==========


@bot.command(name="addlife", help="Add a life to a user (Admin only)")
@admin_only()
async def add_life(ctx, member: discord.Member):
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass

    lives = load_lives()
    # Default to 3 lives if user not found
    current_lives = lives.get(str(member.id), 3)

    if current_lives >= MAX_LIVES:
        embed = discord.Embed(
            title="❤️ Max Lives",
            description=
            (f"{member.mention} already has the maximum of {MAX_LIVES} lives."
             ),
            color=COLORS["success"])
        return await ctx.send(embed=embed, delete_after=30)

    lives[str(member.id)] = current_lives + 1
    save_lives(lives)
    bot.user_lives[member.id] = current_lives + 1

    embed = discord.Embed(
        title="✨ Life Added",
        description=(
            f"{member.mention} got a life added!\n"
            f"Good job on working hard. ❤️ {current_lives + 1}/{MAX_LIVES}"),
        color=COLORS["success"])
    await ctx.send(embed=embed, delete_after=30)


@bot.command(name="removelife", help="Remove a life from a user (Admin only)")
@admin_only()
async def remove_life(ctx, member: discord.Member):
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass

    lives = load_lives()
    # Default to 3 lives if user not found
    current_lives = lives.get(str(member.id), 3)

    if current_lives <= 0:
        embed = discord.Embed(
            title="⚡ Strike Issued",
            description=
            (f"{member.mention} has been hit by a strike!\n"
             f"🚨 You now have 0 lives remaining.\n"
             f"This will result in high penalties that will be discussed in our next meeting."
             ),
            color=COLORS["error"])
        return await ctx.send(embed=embed, delete_after=30)

    lives[str(member.id)] = current_lives - 1
    save_lives(lives)
    bot.user_lives[member.id] = current_lives - 1

    remaining = current_lives - 1
    if remaining > 0:
        message = (f"{member.mention} has been hit by a strike!\n"
                   f"❤️ Remaining lives: {remaining}/{MAX_LIVES}\n"
                   f"Please make sure you're on track.")
        color = COLORS["warning"]
    else:
        message = (
            f"{member.mention} has been hit by a strike!\n"
            f"🚨 You now have 0 lives remaining.\n"
            f"This will result in high penalties that will be discussed in our next meeting."
        )
        color = COLORS["error"]

    embed = discord.Embed(title="⚡ Life Removed",
                          description=message,
                          color=color)
    await ctx.send(embed=embed, delete_after=30)


@bot.command(name="checklives", help="Check your remaining lives")
async def check_lives(ctx, member: discord.Member = None):
    member = member or ctx.author
    current_lives = get_user_lives(member.id)

    embed = discord.Embed(
        title=f"❤️ {member.display_name}'s Lives",
        description=f"Current lives: {current_lives}/{MAX_LIVES}",
        color=COLORS["primary"])
    await ctx.send(embed=embed)


# ========== Modified on_ready ==========


@bot.command(name="mytasks")
async def my_tasks(ctx):
    user_id = ctx.author.id
    tasks = bot.task_assignments.get(user_id, {})

    if not tasks:
        await ctx.send("ℹ️ No Tasks\nYou have no assigned tasks.")
        return

    embed = discord.Embed(title="🗂️ Your Tasks", color=discord.Color.blurple())
    for task_id, task in tasks.items():
        due_date = (datetime.fromisoformat(task["due_date"]).astimezone(EST)
                    if task.get("due_date") else None)
        status = task.get("status", "Pending")
        task_line = (
            f"`#{task_id}` **{task['description']}**\n"
            f"▸ {status} | "
            f"⏰ {due_date.strftime('%b %d %H:%M') if due_date else 'No deadline'} | "
            f"🔮 {task.get('priority', 'Normal').title()} | "
            f"❗ {str(task.get('importance', '1'))} | "
            f"💬 {0} comments")
        embed.add_field(name="\u200b", value=task_line, inline=False)

    await ctx.send(embed=embed)


@bot.command(name="alltasks", help="View all tasks (Admin only)")
@is_admin()
@admin_only()
async def all_tasks(ctx):
    embed = discord.Embed(title="📋 All Assigned Tasks",
                          color=COLORS["primary"])

    for member_id_str, tasks_dict in bot.task_assignments.items():
        member = ctx.guild.get_member(int(member_id_str))
        member_name = member.display_name if member else f"User ID {member_id_str}"

        task_list = []
        for tid, task in tasks_dict.items():
            status = task.get("status", "Pending")
            due = task.get("due_date", "No due date")
            task_list.append(f"`#{tid}` {status} | Due: {due}")

        if task_list:
            embed.add_field(name=f"👤 {member_name} ({len(tasks_dict)} tasks)",
                            value="\n".join(task_list),
                            inline=False)

    if not embed.fields:
        embed.description = "No tasks have been assigned yet."

    await ctx.send(embed=embed)


import re
from datetime import datetime, timedelta
import discord
from discord.ext import commands


@bot.command(name="updatetask")
async def update_task(ctx, *, args=None):
    if not args:
        embed = create_error_embed(
            "Invalid Format",
            "Usage: `!updatetask <task_id> \"new description\" [today|tomorrow|YYYY-MM-DD] [HH:MM] [priority|importance] [points]`\n"
            "Priority can be low, normal, or high. Importance is 1-5. Points is a number."
        )
        return await ctx.send(embed=embed)

    # Regex pattern with groups:
    # task_id "desc" [date] [time] [priority|importance] [points]
    pattern = (
        r'^(\d+)\s+"([^"]+)"'  # task_id and description
        r'(?:\s+(today|tomorrow|\d{4}-\d{2}-\d{2}))?'  # optional date
        r'(?:\s+(\d{2}:\d{2}))?'  # optional time
        r'(?:\s+([a-zA-Z]+)\|(\d))?'  # optional priority|importance
        r'(?:\s+(\d+))?'  # optional points
        r'$')

    match = re.match(pattern, args.strip(), re.IGNORECASE)

    if not match:
        embed = create_error_embed(
            "Invalid Format",
            "Usage: `!updatetask <task_id> \"new description\" [today|tomorrow|YYYY-MM-DD] [HH:MM] [priority|importance] [points]`\n"
            "Example: !updatetask 1 \"Fix bot\" today 14:30 high|4 10")
        return await ctx.send(embed=embed)

    (task_id_str, new_desc, date_word, time_str, priority_str, importance_str,
     points_str) = match.groups()

    task_id = int(task_id_str)
    priority = priority_str.lower() if priority_str else "normal"
    importance = int(importance_str) if importance_str else 1
    points = int(points_str) if points_str else 0

    # Validate importance range
    if not (1 <= importance <= 5):
        embed = create_error_embed("Invalid Importance",
                                   "Importance must be between 1 and 5.")
        return await ctx.send(embed=embed)

    # Handle due date/time
    due_iso = None
    if date_word:
        try:
            if date_word.lower() == "today":
                base_date = datetime.now(EST).date()
            elif date_word.lower() == "tomorrow":
                base_date = datetime.now(EST).date() + timedelta(days=1)
            else:
                base_date = datetime.strptime(date_word, "%Y-%m-%d").date()

            due_time = datetime.strptime(time_str or "00:00", "%H:%M").time()
            due = datetime.combine(base_date, due_time)
            due_iso = EST.localize(due).isoformat()
        except ValueError:
            embed = create_error_embed(
                "Invalid Date/Time",
                "Please use formats like `today`, `tomorrow`, or `YYYY-MM-DD HH:MM`."
            )
            return await ctx.send(embed=embed)

    # Flag to track if updated
    updated = False

    # Update user-created tasks
    for creator_id, tasks in bot.user_tasks_created.items():
        if task_id in tasks:
            tasks[task_id].update({
                'description': new_desc,
                'due_date': due_iso,
                'priority': priority,
                'importance': importance,
                'points': points
            })

            # Also update in task_assignments if exists
            for assignee_id, assigned_tasks in bot.task_assignments.items():
                if task_id in assigned_tasks:
                    assigned_tasks[task_id].update({
                        'description': new_desc,
                        'due_date': due_iso,
                        'priority': priority,
                        'importance': importance,
                        'points': points
                    })

            # Save both dicts after update
            save_tasks(bot.user_tasks_created)
            save_tasks(bot.task_assignments)

            updated = True
            break  # stop searching after found

    # If not found in user_tasks_created, try task_assignments directly
    if not updated:
        for assignee_id, tasks in bot.task_assignments.items():
            if task_id in tasks:
                tasks[task_id].update({
                    'description': new_desc,
                    'due_date': due_iso,
                    'priority': priority,
                    'importance': importance,
                    'points': points
                })

                save_tasks(bot.task_assignments)
                updated = True
                break

    if updated:
        embed = discord.Embed(title=f"✅ Task #{task_id} Updated",
                              color=COLORS["success"])
        embed.add_field(name="Description", value=new_desc, inline=False)
        embed.add_field(name="Due Date",
                        value=due_iso or "Not specified",
                        inline=True)
        embed.add_field(name="Priority",
                        value=priority.capitalize(),
                        inline=True)
        embed.add_field(name="Importance", value=str(importance), inline=True)
        embed.add_field(name="Points", value=str(points), inline=True)
        await update_task_channel()
        return await ctx.send(embed=embed)
    else:
        embed = create_error_embed(
            "Not Found", f"Task ID {task_id} not found in your tasks.")
        await ctx.send(embed=embed)


@bot.command(name="commenttask",
             help="Add comment to a task: !commenttask <task ID> <comment>")
async def comment_task(ctx, task_id: int, *, comment: str):
    # Check if task exists in any user's assignments
    task_exists = any(task_id in tasks
                      for tasks in bot.task_assignments.values())

    if not task_exists:
        embed = create_error_embed("Not Found",
                                   "Task ID not found in the system.")
        return await ctx.send(embed=embed)

    comments = load_comments()
    task_comments = comments.get(str(task_id), [])
    task_comments.append({
        "author_id": ctx.author.id,
        "author_name": ctx.author.display_name,
        "comment": comment,
        "timestamp": datetime.now(EST).isoformat()
    })
    comments[str(task_id)] = task_comments
    save_comments(comments)

    embed = create_success_embed(
        "Comment Added", f"Your comment has been added to task #{task_id}.")
    await ctx.send(embed=embed)
    await update_task_channel()


@bot.command(name="health", help="View your daily logs in a beautiful format")
async def health(ctx, member: discord.Member = None):
    member = member or ctx.author

    # Permission check
    if member != ctx.author and ctx.author.id != ADMIN_ID:
        embed = discord.Embed(
            title="⛔ Access Denied",
            description=f"You can't view {member.display_name}'s logs",
            color=COLORS["error"])
        return await ctx.send(embed=embed, delete_after=10)

    logs = load_logs()
    user_logs = logs.get(str(member.id), {})

    if not user_logs:
        embed = discord.Embed(
            title="📭 No Logs Found",
            description=f"{member.display_name} hasn't logged anything yet!",
            color=COLORS["warning"])
        return await ctx.send(embed=embed, view=LogButton())

    # Create paginated view
    view = HealthLogsView(member.id, user_logs)
    embed = view.create_embed()
    await ctx.send(embed=embed, view=view)


@bot.command(name="adminlog",
             help="Admin: Add a log entry for a user with optional date")
@is_admin()
async def admin_log(ctx,
                    member: discord.Member,
                    date: Optional[str] = None,
                    *,
                    message: str):
    try:
        user_id = str(member.id)
        log_date = parse_flexible_date(date) if date else str(
            datetime.now(EST).date())

        logs = load_logs()

        if user_id not in logs:
            logs[user_id] = {}

        if log_date not in logs[user_id]:
            logs[user_id][log_date] = []
        elif isinstance(logs[user_id][log_date], str):
            logs[user_id][log_date] = [{
                "timestamp": "converted",
                "log": logs[user_id][log_date]
            }]

        logs[user_id][log_date].append({
            "timestamp":
            datetime.now(EST).isoformat(),
            "log":
            message
        })

        save_logs(logs)

        # Award 2 points for logging
        award_points(user_id, f"daily_log_{log_date}", 2,
                     f"Completed log for {log_date}")

        # Delete admin's command message
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

        await ctx.send(
            f"✅ Log added for {member.mention} on {log_date} (+2 points)")
        await update_leaderboard_channel()

    except Exception as e:
        error_embed = discord.Embed(title="❌ Command Error",
                                    description=f"An error occurred: {e}",
                                    color=COLORS["error"])
        await ctx.send(embed=error_embed)


@bot.command(name="log", help="Log your daily work (+2 points)")
async def log(ctx, *, message: str):
    try:
        user_id = str(ctx.author.id)
        today = str(datetime.now(EST).date())

        logs = load_logs()

        if user_id not in logs:
            logs[user_id] = {}

        if today not in logs[user_id]:
            logs[user_id][today] = []
        elif isinstance(logs[user_id][today], str):
            logs[user_id][today] = [{
                "timestamp": "converted",
                "log": logs[user_id][today]
            }]

        logs[user_id][today].append({
            "timestamp": datetime.now(EST).isoformat(),
            "log": message
        })

        save_logs(logs)

        # Award 2 points for daily logging
        award_points(user_id, f"daily_log_{today}", 2,
                     f"Completed log for {today}")

        embed = discord.Embed(
            title="✅ Log Saved (+2 points)",
            description=f"Your work for {today} has been recorded!",
            color=COLORS["success"])
        await ctx.send(embed=embed)
        await update_leaderboard_channel()

    except Exception as e:
        error_embed = discord.Embed(title="❌ Command Error",
                                    description=f"An error occurred: {e}",
                                    color=COLORS["error"])
        await ctx.send(embed=error_embed)


@bot.command(name="resetlogs",
             help="""Reset logs for a user or date (admin only)
Examples:
!resetlogs @user - Reset all logs for a user
!resetlogs 25 May - Reset logs for all users on May 25
!resetlogs @user 25 May - Reset logs for specific user on May 25""")
@is_admin()
@admin_only()
async def reset_logs(ctx, *, args: str = None):
    """Reset logs for a specific user, date, or combination of both."""
    logs = load_logs()

    # Validate input
    if not args:
        embed = discord.Embed(
            title="❌ Invalid Usage",
            description=
            "You must specify at least a user or a date to reset logs.\nExamples:\n• `!resetlogs @user` - Reset all logs for a user\n• `!resetlogs 25 May` - Reset logs for all users on May 25\n• `!resetlogs @user 25 May` - Reset logs for specific user on May 25",
            color=COLORS["error"])
        await ctx.send(embed=embed)
        return

    try:
        # Initialize variables
        member = None
        date_key = None

        # Check if the input contains a user mention
        if ctx.message.mentions:
            member = ctx.message.mentions[0]
            date_part = args.replace(member.mention, "").strip()
        else:
            date_part = args.strip()

        # Parse date if there's a date part
        if date_part:
            try:
                date_key = parse_flexible_date(date_part)
            except ValueError as e:
                await ctx.send(f"❌ Invalid date: {str(e)}")
                return

        # Case 1: Reset all logs for a specific user
        if member and not date_key:
            target_id = str(member.id)
            if target_id not in logs or not logs[target_id]:
                await ctx.send(f"📭 No logs found for {member.display_name}.")
                return

            del logs[target_id]
            save_logs(logs)
            await ctx.send(
                f"✅ All logs for {member.display_name} have been reset.")
            return

        # Case 2: Reset logs for specific user on specific date
        elif member and date_key:
            target_id = str(member.id)
            if target_id not in logs:
                await ctx.send(f"📭 No logs found for {member.display_name}.")
                return

            if date_key not in logs[target_id]:
                await ctx.send(
                    f"📭 No logs found for {member.display_name} on {date_key}."
                )
                return

            del logs[target_id][date_key]
            save_logs(logs)
            await ctx.send(
                f"✅ Logs for {member.display_name} on {date_key} have been reset."
            )
            return

        # Case 3: Reset logs for all users on specific date
        elif date_key and not member:
            removed_any = False
            for user_id in list(logs.keys()):
                if date_key in logs[user_id]:
                    del logs[user_id][date_key]
                    removed_any = True

            if removed_any:
                save_logs(logs)
                await ctx.send(
                    f"✅ Logs on {date_key} have been reset for all users.")
            else:
                await ctx.send(f"📭 No logs found on {date_key}.")
                return

        # If we get here, no valid case was matched
        await ctx.send(
            "❌ Invalid command usage. See !help resetlogs for examples.")

    except Exception as e:
        error_embed = discord.Embed(title="❌ Error Resetting Logs",
                                    description=f"An error occurred: {str(e)}",
                                    color=COLORS["error"])
        await ctx.send(embed=error_embed)


@bot.command(name="removetask")
@is_admin()
@admin_only()
async def remove_task(ctx, *, args: str = None):
    """Remove tasks for a specific user, task ID, or both."""
    if not args:
        embed = discord.Embed(
            title="❌ Invalid Usage",
            description=
            "You must specify at least a user or task ID.\nExamples:\n"
            "• `!removetask @user` - Remove all tasks for a user\n"
            "• `!removetask 123` - Remove task with ID 123\n"
            "• `!removetask @user 123` - Remove task 123 for that user",
            color=COLORS["error"])
        await ctx.send(embed=embed)
        return

    try:
        member = None
        task_id = None

        # Extract mentioned user
        if ctx.message.mentions:
            member = ctx.message.mentions[0]
            args = args.replace(member.mention, "").strip()

        # Extract task ID
        if args:
            try:
                task_id = int(args.split()[0])
            except ValueError:
                await ctx.send("❌ Task ID must be a number.")
                return

        # Case 1: @user only
        if member and task_id is None:
            target_id = str(member.id)
            if target_id not in bot.task_assignments or not bot.task_assignments[
                    target_id]:
                await ctx.send(f"📭 No tasks found for {member.display_name}.")
                return

            count = len(bot.task_assignments[target_id])
            del bot.task_assignments[target_id]
            save_tasks(bot.task_assignments)
            await ctx.send(
                f"✅ Removed all {count} tasks for {member.display_name}.")
            await update_task_channel()
            return

        # Case 2: task ID only
        if task_id is not None and member is None:
            found = False
            for user_id, tasks in list(bot.task_assignments.items()):
                if task_id in tasks:
                    del tasks[task_id]
                    member = await bot.fetch_user(int(user_id))
                    if not tasks:
                        del bot.task_assignments[user_id]
                    found = True
                    break

            if found:
                save_tasks(bot.task_assignments)
                await ctx.send(
                    f"✅ Removed task {task_id} (assigned to {member.display_name})."
                )
                await update_task_channel()
            else:
                await ctx.send(f"📭 Task ID {task_id} not found.")
            return

        # Case 3: @user and task ID
        if member and task_id is not None:
            target_id = member.id
            if target_id not in bot.task_assignments or task_id not in bot.task_assignments[
                    target_id]:
                await ctx.send(
                    f"📭 Task ID {task_id} not found for {member.display_name}."
                )
                return

            del bot.task_assignments[target_id][task_id]
            if not bot.task_assignments[target_id]:
                del bot.task_assignments[target_id]
            save_tasks(bot.task_assignments)
            await ctx.send(
                f"✅ Removed task {task_id} for {member.display_name}.")
            await update_task_channel()
            return

        await ctx.send("❌ Invalid command usage. Try `!help removetask`.")

    except Exception as e:
        error_embed = discord.Embed(title="❌ Error Removing Task",
                                    description=f"An error occurred: {str(e)}",
                                    color=COLORS["error"])
        await ctx.send(embed=error_embed)


@bot.command(name="searchtasks",
             help="Search your tasks: !searchtasks <keyword>")
async def search_tasks(ctx, *, keyword: str):
    user_tasks = bot.task_assignments.get(ctx.author.id, {})
    if not user_tasks:
        embed = create_info_embed("No Tasks", "You have no assigned tasks.")
        return await ctx.send(embed=embed)

    matching_tasks = []
    for tid, task in user_tasks.items():
        if keyword.lower() in task["description"].lower():
            matching_tasks.append((tid, task))

    if not matching_tasks:
        embed = create_info_embed("No Matches",
                                  f"No tasks found containing '{keyword}'")
        return await ctx.send(embed=embed)

    embed = discord.Embed(
        title=f"🔍 Task Search Results for '{keyword}'",
        description=f"Found {len(matching_tasks)} matching tasks",
        color=COLORS["primary"])

    for tid, task in matching_tasks:
        status = task.get("status", "Pending")
        due = task.get("due_date", "No due date")
        embed.add_field(name=f"Task #{tid} - {status}",
                        value=f"**{task['description']}**\nDue: {due}",
                        inline=False)

    await ctx.send(embed=embed)
    await update_task_channel()


@bot.command(name="taskdebug")
@is_admin()
async def task_debug(ctx):
    """Debug the task storage system"""
    embed = discord.Embed(title="Task System Debug", color=COLORS["primary"])

    # Show how user IDs are stored
    id_types = {}
    for user_id in bot.task_assignments.keys():
        id_type = type(user_id).__name__
        id_types[id_type] = id_types.get(id_type, 0) + 1

    embed.add_field(name="User ID Storage Types",
                    value="\n".join(f"{k}: {v}" for k, v in id_types.items()),
                    inline=False)

    # Show specific tasks for the command author
    str_id = str(ctx.author.id)
    int_id = ctx.author.id
    author_tasks = []

    if str_id in bot.task_assignments:
        author_tasks.extend(bot.task_assignments[str_id].items())
    if int_id in bot.task_assignments:
        author_tasks.extend(bot.task_assignments[int_id].items())

    if author_tasks:
        task_list = "\n".join(f"ID {tid}: {task['description']}"
                              for tid, task in author_tasks)
        embed.add_field(name=f"Your Tasks ({len(author_tasks)})",
                        value=task_list,
                        inline=False)
    else:
        embed.add_field(name="Your Tasks",
                        value="No tasks found under either ID type",
                        inline=False)

    await ctx.send(embed=embed)


# 4. Task Categories
@bot.command(
    name="addcategory",
    help="Add a category to a task: !addcategory <task ID> <category>")
async def add_category(ctx, task_id: int, *, category: str):
    user_tasks = bot.task_assignments.get(ctx.author.id, {})
    if task_id not in user_tasks:
        embed = create_error_embed("Not Found",
                                   "Task ID not found in your assignments.")
        return await ctx.send(embed=embed)

    task = user_tasks[task_id]
    if "categories" not in task:
        task["categories"] = []

    if category.lower() not in [c.lower() for c in task["categories"]]:
        task["categories"].append(category)
        save_tasks(bot.task_assignments)
        embed = create_success_embed(
            "Category Added",
            f"Added category '{category}' to task #{task_id}")
    else:
        embed = create_info_embed(
            "Category Exists",
            f"Task #{task_id} already has category '{category}'")

    await ctx.send(embed=embed)
    await update_task_channel()


from datetime import datetime, timedelta


@tasks.loop(minutes=10)
async def check_due_dates():
    now = datetime.now(EST)

    for user_id, tasks in bot.task_assignments.items():
        try:
            member = await bot.fetch_user(int(user_id))
        except discord.NotFound:
            continue

        for task_id, task in tasks.items():
            if task.get("status") == "Completed":
                continue

            if not task.get("due_date"):
                continue

            try:
                due_date = datetime.fromisoformat(task["due_date"])
                if due_date.tzinfo is None:
                    due_date = EST.localize(due_date)

                time_left = due_date - now
                if time_left.total_seconds() <= 0:
                    # Overdue handling
                    if not task.get("reminded_overdue"):
                        await send_reminder(member, task_id, task, "overdue")
                        task["reminded_overdue"] = True
                else:
                    # Future due date handling
                    hours_left = time_left.total_seconds() / 3600

                    if 24 <= hours_left < 25 and not task.get("reminded_24h"):
                        await send_reminder(member, task_id, task, "24h")
                        task["reminded_24h"] = True
                    elif 1 <= hours_left < 2 and not task.get("reminded_1h"):
                        await send_reminder(member, task_id, task, "1h")
                        task["reminded_1h"] = True

            except Exception as e:
                print(f"Error checking task {task_id}: {e}")

    save_tasks(bot.task_assignments)


async def send_reminder(member, task_id, task, reminder_type):
    channel = bot.get_channel(TASK_CHANNEL_ID)
    if not channel:
        return

    messages = {
        "24h": f"🔔 Task #{task_id} is due in 24 hours!",
        "1h": f"⏰ Task #{task_id} is due in 1 hour!",
        "overdue": f"🚨 Task #{task_id} is overdue!"
    }

    embed = discord.Embed(title=messages[reminder_type],
                          description=task["description"],
                          color=COLORS["error"]
                          if reminder_type == "overdue" else COLORS["warning"])
    await channel.send(f"{member.mention}", embed=embed)


# 5. Weekly Summary


@tasks.loop(minutes=1)
async def weekly_summary():
    await bot.wait_until_ready()

    now = datetime.now(EST)
    if now.weekday() == 6 and now.hour == 18 and now.minute == 0:
        channel = bot.get_channel(CHANNEL_ID)
        if channel is None:
            return

        logs = load_logs()
        if not logs:
            return

        embed = discord.Embed(title="📊 Weekly Summary",
                              description="Here's the weekly activity report",
                              color=COLORS["neutral"],
                              timestamp=now)

        user_log_counts = {
            uid: len(user_logs)
            for uid, user_logs in logs.items()
        }
        sorted_users = sorted(user_log_counts.items(),
                              key=lambda x: x[1],
                              reverse=True)

        if sorted_users:
            embed.add_field(name="🏆 Top Contributors",
                            value="\n".join(
                                f"<@{uid}>: {count} logs"
                                for uid, count in sorted_users[:3]),
                            inline=False)

        completed_tasks = sum(1
                              for user_tasks in bot.task_assignments.values()
                              for task in user_tasks.values()
                              if task.get("status") == "Completed")

        embed.add_field(name="✅ Completed Tasks",
                        value=f"{completed_tasks} tasks completed this week",
                        inline=True)

        embed.set_footer(text="Great work everyone! Keep it up!")
        await channel.send(embed=embed)

@bot.command(name="forework",
             help="Ping users who haven't logged today (admin only)")
@admin_only()
async def forework(ctx):
    """Admin-only command to ping users who haven't logged work for the current day."""
    # If not admin, silently delete the message
    if ctx.author.id != ADMIN_ID:
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
        return

    logs = load_logs()
    today = datetime.now(EST).strftime('%Y-%m-%d')

    # Get list of all guild members excluding bots
    missing_users = [
        member.mention for member in ctx.guild.members
        if not member.bot and str(member.id) not in logs
        or today not in logs.get(str(member.id), {})
    ]

    if not missing_users:
        embed = discord.Embed(
            title="✅ All Clear!",
            description="Everyone has logged work for today.",
            color=COLORS["success"])
        return await ctx.send(embed=embed)

    # Ping missing users
    mention_text = " ".join(missing_users)
    embed = discord.Embed(
        title="📢 Reminder to Log Your Work!",
        description=
        "The following members haven't logged their work for today:\n" +
        mention_text,
        color=COLORS["warning"])
    await ctx.send(embed=embed)


    # 7. Backup System
@bot.command(name="backup", help="Create a backup of all data (Admin only)")
@admin_only()
@is_admin()
async def create_backup(ctx):
    # Create backup directory if it doesn't exist
    backup_dir = "backups"
    os.makedirs(backup_dir, exist_ok=True)

    # Create timestamped backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f"backup_{timestamp}.zip")

    # Files to include in backup
    files_to_backup = [LOG_FILE, TASKS_FILE, COMMENTS_FILE]

    # Create zip archive
    with zipfile.ZipFile(backup_file, 'w') as zipf:
        for file in files_to_backup:
            if os.path.exists(file):
                zipf.write(file)

    # Send backup to admin
    embed = create_success_embed(
        "Backup Created",
        f"Successfully created backup with {len(files_to_backup)} data files.")
    await ctx.send(embed=embed, file=discord.File(backup_file))

    # Clean up
    os.remove(backup_file)


@bot.command(name="exportlogs", help="Export your logs as a text file")
async def export_logs(ctx):
    logs = load_logs()
    user_logs = logs.get(str(ctx.author.id), {})

    if not user_logs:
        embed = create_info_embed("No Logs", "You have no logs to export.")
        return await ctx.send(embed=embed)

    export_content = f"Work Logs for {ctx.author.display_name}\n\n"
    for date, entry in sorted(user_logs.items(), reverse=True):
        formatted_date = datetime.strptime(date,
                                           "%Y-%m-%d").strftime("%B %d, %Y")
        export_content += f"=== {formatted_date} ===\n"

        try:
            # Step 1: Ensure it's not already a list
            if isinstance(entry, str):
                entry = ast.literal_eval(entry)

            # Step 2: Entry might still be a list of strings with nested logs
            for item in entry:
                # If item itself is a dict with a 'log' key that is a stringified list
                if isinstance(item, dict) and isinstance(item.get("log"), str):
                    nested_logs = ast.literal_eval(item["log"])
                else:
                    nested_logs = entry

                # Step 3: Now go through actual logs
                for log_entry in nested_logs:
                    timestamp = datetime.fromisoformat(log_entry["timestamp"])
                    time_str = timestamp.strftime("%H:%M")
                    log_text = log_entry["log"].strip('"')
                    export_content += f"[{time_str}] {log_text}\n"
                break  # we processed the nested logs; no need to loop again

        except Exception as e:
            export_content += f"[Invalid Entry] {entry}\n"

        export_content += "\n"

    with open("temp_export.txt", "w", encoding="utf-8") as f:
        f.write(export_content)

    embed = create_success_embed(
        "Export Ready", "Your logs have been exported as a text file.")
    await ctx.author.send(embed=embed, file=discord.File("temp_export.txt"))

    os.remove("temp_export.txt")
    await ctx.message.add_reaction("✅")


@bot.command(name="viewcomments",
             help="View comments on a task: !viewcomments <task ID>")
async def view_comments(ctx, task_id: int):
    # Check if task exists in the system
    task_exists = any(task_id in tasks
                      for tasks in bot.task_assignments.values())

    if not task_exists:
        embed = create_error_embed("Not Found",
                                   "Task ID not found in the system.")
        return await ctx.send(embed=embed)

# Load comments
    comments = load_comments()
    task_comments = comments.get(str(task_id), [])

    if not task_comments:
        embed = create_info_embed("No Comments",
                                  f"No comments found for task #{task_id}.")
        return await ctx.send(embed=embed)

# Create paginated embed
    embed = discord.Embed(title=f"📝 Comments for Task #{task_id}",
                          color=COLORS["primary"])

    # Add up to 5 comments per embed (Discord limit)
    for comment in task_comments[:5]:
        timestamp = datetime.fromisoformat(
            comment["timestamp"]).strftime("%b %d, %Y %I:%M %p")
        embed.add_field(name=f"{comment['author_name']} on {timestamp}",
                        value=comment["comment"],
                        inline=False)

# Add footer with total comment count
    embed.set_footer(
        text=
        f"Showing {len(task_comments[:5])} of {len(task_comments)} comments")

    # If more than 5 comments, add navigation buttons
    if len(task_comments) > 5:
        embed.set_footer(
            text=
            f"Showing first 5 of {len(task_comments)} comments - More comments available"
        )

    await ctx.send(embed=embed)


# 9. Task Priority Visualization
@bot.command(name="taskchart", help="Visualize your tasks by priority")
async def task_chart(ctx):
    user_tasks = bot.task_assignments.get(ctx.author.id, {})
    if not user_tasks:
        embed = create_info_embed("No Tasks", "You have no assigned tasks.")
        return await ctx.send(embed=embed)

    # Count tasks by priority
    priority_counts = {"High": 0, "Normal": 0, "Low": 0}
    for task in user_tasks.values():
        priority = task.get("priority", "Normal").capitalize()
        priority_counts[priority] += 1

    # Generate ASCII chart
    max_count = max(
        priority_counts.values()) if priority_counts.values() else 1
    chart = ""
    for priority, count in priority_counts.items():
        bar_length = int(20 * count / max_count) if max_count > 0 else 0
        chart += f"{priority}: {'▮' * bar_length} {count}\n"

    embed = discord.Embed(title="📊 Your Tasks by Priority",
                          description=f"```\n{chart}\n```",
                          color=COLORS["primary"])
    embed.set_footer(text=f"Total tasks: {len(user_tasks)}")
    await ctx.send(embed=embed)
    await update_task_channel()


@bot.command(name="removebadge", help="Remove a badge from a user (admin only)")
@is_admin()
async def remove_badge(ctx, member: discord.Member, badge_id: str):
    user_badges = load_user_badges()
    user_id_str = str(member.id)
    
    if user_id_str not in user_badges or badge_id not in user_badges[user_id_str]:
        return await ctx.send(f"❌ {member.display_name} does not have the badge with ID `{badge_id}`.")
    
    user_badges[user_id_str].remove(badge_id)
    # Save changes
    with open("user_badges.json", "w") as f:  # Adjust filename if needed
        json.dump(user_badges, f, indent=4)
    
    await ctx.send(f"✅ Removed badge `{badge_id}` from {member.display_name}.")


@bot.command(name="sync", help="testing sync" )
@is_admin()
async def sync(ctx):
    await bot.tree.sync()
    await ctx.send("Commands synced!")

# 10. Task Reminder Configuration
@bot.command(name="taskreminders", help="Configure your task reminders")
async def task_reminders(ctx, frequency: str = None):
    if not frequency:
        # Show current settings
        embed = create_info_embed(
            "Task Reminders", "Current reminder settings: Daily at 6PM EST\n"
            "Usage: `!taskreminders <off/daily/weekly>`")
        return await ctx.send(embed=embed)

    frequency = frequency.lower()
    if frequency == "off":
        # Disable reminders
        embed = create_success_embed(
            "Reminders Off", "You will no longer receive task reminders.")
    elif frequency == "daily":
        # Enable daily reminders
        embed = create_success_embed(
            "Daily Reminders",
            "You'll receive daily task reminders at 6PM EST.")
    elif frequency == "weekly":
        # Enable weekly reminders
        embed = create_success_embed(
            "Weekly Reminders",
            "You'll receive weekly task reminders on Mondays at 10AM EST.")
    else:
        embed = create_error_embed("Invalid Option",
                                   "Please use: off, daily, or weekly")

    await ctx.send(embed=embed)
    await update_task_channel()

    # ========== Startup ==========


if __name__ == "__main__":
    # Load additional data
    try:
        with open("scores.json", "r") as f:
            bot.user_scores = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        bot.user_scores = {}

    try:
        keep_alive()
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("\nBot shutting down...")
    except Exception as e:
        print(f"Error starting bot: {e}")
