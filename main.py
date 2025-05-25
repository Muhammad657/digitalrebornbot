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
# ========== Setup ==========
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = 1359688450445541559  # Your channel id here
ADMIN_ID = 1199446551391633523  # Replace with actual admin user ID
EST = pytz.timezone('US/Eastern')
# Color Palette
COLORS = {
    "primary": 0x5865F2,  # Discord blurple
    "success": 0x57F287,  # Discord green
    "warning": 0xFEE75C,  # Discord yellow
    "error": 0xED4245,  # Discord red
    "neutral": 0xEB459E,  # Discord pink
    "dark": 0x23272A,  # Discord dark
    "light": 0xFFFFFF  # White
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
        # Remove default help command to implement custom one
        self.help_command = None


bot = TaskBot(command_prefix="!", intents=intents, case_insensitive=True)


def is_admin():

    def predicate(ctx):
        return ctx.author.id == ADMIN_ID

    return commands.check(predicate)


# ========== File Handling ==========
LOG_FILE = "daily_logs.json"
TASKS_FILE = "tasks.json"
COMMENTS_FILE = "comments.json"


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


class HealthLogsView(discord.ui.View):

    def __init__(self, user_id: int, logs: Dict[str, str]):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.logs = sorted(logs.items(), key=lambda x: x[0],
                           reverse=True)  # Newest first
        self.page = 0
        self.max_per_page = 5
        self.total_pages = max(1, (len(self.logs) + self.max_per_page - 1) //
                               self.max_per_page)  # Fixed calculation

    def get_page_content(self):
        start = self.page * self.max_per_page
        end = start + self.max_per_page
        page_logs = self.logs[start:end]

        desc = ""
        for date, entries in page_logs:
            try:
                # Format date
                try:
                    date_obj = datetime.strptime(date, "%Y-%m-%d")
                    formatted_date = date_obj.strftime("%A, %B %d, %Y")
                except ValueError:
                    formatted_date = date

                desc += "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                desc += f"📅 **{formatted_date}**\n"

                # Ensure entries is a list of logs
                if isinstance(entries, str):
                    entries = [{"timestamp": "converted", "log": entries}]
                elif isinstance(entries, dict) and "log" in entries:
                    entries = [entries]

                for entry in entries:
                    desc += f"```\n{entry['log']}\n```\n"

            except Exception as e:
                print(f"Error formatting log {date}: {e}")
                continue

        return desc or "No logs to show."

    @discord.ui.button(label="◄ Previous", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction,
                            button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            embed = self.create_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Next ►", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction,
                        button: discord.ui.Button):
        if self.page < self.total_pages - 1:
            self.page += 1
            embed = self.create_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="📝 Log Work",
                       style=discord.ButtonStyle.primary,
                       emoji="✏️")
    async def log_work_button(self, interaction: discord.Interaction,
                              button: discord.ui.Button):
        await interaction.response.send_modal(LogModal())

    def create_embed(self):
        member = bot.get_user(self.user_id)
        embed = discord.Embed(
            title=
            f"📊 Work Logs for {member.display_name if member else 'Unknown User'}",
            description=self.get_page_content(),
            color=COLORS["primary"],
            timestamp=datetime.now(EST))

        if member and member.avatar:
            embed.set_thumbnail(url=member.avatar.url)

        embed.set_footer(
            text=
            f"Page {self.page + 1}/{self.total_pages} • {datetime.now().strftime('%m/%d/%Y %I:%M %p')}",
            icon_url="https://i.imgur.com/7W0MJXP.png")
        return embed


@bot.event
async def on_command_error(ctx, error):
    # Ignore CheckFailure for admin commands (they're already handled silently)
    if isinstance(error, commands.CheckFailure):
        return

    # Handle other errors normally
    embed = discord.Embed(title="❌ Command Error", color=COLORS["error"])

    if isinstance(error, commands.CommandNotFound):
        embed.description = "Command not found. Type `!help` to see available commands."
    elif isinstance(error, commands.MissingPermissions):
        embed.description = "You don't have permission to use this command."
    else:
        embed.description = f"An error occurred: {str(error)}"

    await ctx.send(embed=embed)


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


# ========== Scheduled Tasks ==========
@tasks.loop(time=time(18, 0))  # 6 PM UTC reminder to log work
async def daily_log_reminder():
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        return

    today = str(datetime.now(EST).date())
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


@tasks.loop(time=time(0,
                      0))  # Midnight reset logs and send summary DM to admin
async def send_summary_to_admin():
    await bot.wait_until_ready()
    logs = load_logs()
    admin = bot.get_user(ADMIN_ID)
    if admin is None:
        print("Admin user not found!")
        return

    if not logs:
        embed = create_info_embed("Daily Summary",
                                  "No logs to show for today.")
        await admin.send(embed=embed)
    else:
        for user_id, user_log in logs.items():
            user = bot.get_user(int(user_id))
            mention = user.mention if user else f"<User ID: {user_id}>"

            embed = discord.Embed(title=f"📊 Daily Logs Summary - {mention}",
                                  color=COLORS["primary"],
                                  timestamp=datetime.now(EST))

            for date, desc in sorted(user_log.items(), reverse=True):
                embed.add_field(name=f"📅 {date}", value=desc, inline=False)

            embed.set_footer(text="End of summary")
            await admin.send(embed=embed)

    # Reset logs
    # save_logs({})


@tasks.loop(minutes=60)
async def evening_ping_task():
    now = datetime.now(EST).time()
    if now < time(16, 0):
        return

    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        return

    today = str(datetime.now(EST).date())
    user_logs = load_logs()
    guild = channel.guild
    members = [m for m in guild.members if not m.bot]

    slackers = [
        m.mention for m in members
        if str(m.id) not in user_logs or today not in user_logs[str(m.id)]
    ]

    if slackers:
        embed = discord.Embed(
            title="⚠️ Hourly Reminder After 8PM UTC",
            description=
            f"The following users haven't logged their work today: {', '.join(slackers)}",
            color=COLORS["warning"])
        embed.add_field(name="Action Required",
                        value="Click below or use `!log` to log your work.",
                        inline=False)
        await channel.send(embed=embed, view=LogButton())
    else:
        evening_ping_task.stop()


@tasks.loop(hours=1)
async def check_overdue_tasks():
    await bot.wait_until_ready()
    tasks_data = load_tasks()
    now = datetime.now(EST).date()
    channel = bot.get_channel(CHANNEL_ID)
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

    @bot.event
    async def on_ready():
        if hasattr(bot, '_ready_called'):
            print("⚠️ Duplicate bot instance detected - shutting down")
            await bot.close()
            return

        bot._ready_called = True
        print(f'Logged in as {bot.user} (ID: {bot.user.id})')

    if not weekly_summary.is_running():
        weekly_summary.start()
    if not evening_ping_task.is_running():
        evening_ping_task.start()
    if bot._ready_called:
        return
    migrate_logs()
    bot._ready_called = True

    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    # Register persistent view
    bot.add_view(LogButton())

    # Initialize task tracking
    bot.task_assignments = load_tasks()
    bot.user_tasks_created = {}

    # Load existing task counter
    if bot.task_assignments:
        max_id = max(
            max(map(int, user_tasks.keys()))
            for user_tasks in bot.task_assignments.values() if user_tasks)
        bot.task_counter = max_id

    # Start tasks
    if not daily_log_reminder.is_running():
        daily_log_reminder.start()
    if not send_summary_to_admin.is_running():
        send_summary_to_admin.start()
    if not evening_ping_task.is_running():
        evening_ping_task.start()
    if not check_overdue_tasks.is_running():
        check_overdue_tasks.start()
    if not daily_reset_responders.is_running():
        daily_reset_responders.start()


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


@bot.command(name="help")
async def custom_help(ctx, command_name: str = None):
    # Define admin commands (these will be hidden from regular users)
    admin_commands = {
        "assign": "Assign a task to a member",
        "forcework": "Ping everyone who hasn't logged work today",
        "snooze": "Snooze your daily log reminder for X minutes",
        "alllogs": "View all users' logs",
        "forework": "Ping users who haven't logged today",
        "backup": "Create a backup of all data",
        "alltasks": "View all tasks in the system",
        "resetlogs":
        "Reset logs for a user or date\n Examples:\n !resetlogs @user - Reset all logs for a user \n!resetlogs 25 May - Reset logs for all users on May 25\n!resetlogs @user 25 May - Reset logs for specific user on May 25",
        "completetask": "Mark a task as completed",
    }

    # Define regular commands
    regular_commands = {
        # Logging Commands
        "log": "Log your daily work",
        "viewlogs":
        "View your logs or another user's logs (admin only for others)",
        "editlog": "Edit your last log from a specific date",
        "health": "View your daily logs in a beautiful format",
        "exportlogs": "Export your logs as a text file",

        # Task Commands
        "addtask": "Add a new task",
        "mytasks": "View your assigned tasks",
        "updatetask": "Update a task's details",
        "commenttask": "Add comment to a task",
        "viewcomments": "View comments on a task",
        "searchtasks": "Search your tasks by keyword",
        "addcategory": "Add a category to a task",
        "taskchart": "Visualize your tasks by priority",
        "taskreminders": "Configure your task reminders",

        # Gamification & Profile
        "leaderboard": "Show the top contributors",
        "profile": "View your profile and stats"
    }

    if command_name:
        cmd_name = command_name.strip().lower()

        # Check if it's an admin command first
        if cmd_name in admin_commands:
            if ctx.author.id == ADMIN_ID:
                # Send detailed help in DM
                try:
                    await ctx.message.delete()
                except discord.Forbidden:
                    pass

                embed = discord.Embed(title=f"📘 Admin Help: `{cmd_name}`",
                                      description=admin_commands[cmd_name],
                                      color=COLORS["primary"])

                # Add usage examples for specific commands
                if cmd_name == "assign":
                    embed.add_field(name="Usage",
                                    value="`!assign @member task_id`",
                                    inline=False)
                elif cmd_name == "forcework":
                    embed.add_field(
                        name="Usage",
                        value=
                        "`!forcework` - Pings all users who haven't logged today",
                        inline=False)

                try:
                    await ctx.author.send(embed=embed)
                except discord.Forbidden:
                    await ctx.send(
                        f"⚠️ {ctx.author.mention}, I couldn't send you the help in DM. Check your privacy settings.",
                        delete_after=10)
                return
            else:
                # Non-admin tried to view admin command help - delete their message
                try:
                    await ctx.message.delete()
                except discord.Forbidden:
                    pass
                return

        # Handle regular command help
        cmd = bot.get_command(cmd_name)
        if not cmd:
            await ctx.send(f"❌ No command named `{command_name}` found.")
            return

        embed = discord.Embed(title=f"📘 Help: `{cmd.name}`",
                              description=regular_commands.get(
                                  cmd_name, "No description available"),
                              color=COLORS["primary"])

        # Add specific usage examples
        if cmd_name == "log":
            embed.add_field(
                name="Usage",
                value="`!log \"What I did today\"` or click the log button",
                inline=False)
        elif cmd_name == "addtask":
            embed.add_field(
                name="Usage",
                value=
                "`!addtask \"description\" [due_date] [priority]`\nExample: `!addtask \"Fix login bug\" 2023-12-31 high`",
                inline=False)

        await ctx.send(embed=embed)
        return

    # No command specified - show general help
    embed = discord.Embed(
        title="📚 TaskBot Help Menu",
        description="Use `!help <command>` for detailed info on any command.",
        color=COLORS["primary"])

    # Add regular command categories
    embed.add_field(
        name="📝 Logging Commands",
        value="`log`, `viewlogs`, `editlog`, `health`, `exportlogs`",
        inline=False)

    embed.add_field(
        name="📋 Task Commands",
        value=
        "`addtask`, `mytasks`, `updatetask`, `completetask`, `commenttask`, `viewcomments`, `searchtasks`, `addcategory`, `taskchart`, `taskreminders`",
        inline=False)

    embed.add_field(name="🏆 Gamification",
                    value="`leaderboard`, `profile`",
                    inline=False)

    await ctx.send(embed=embed)

    # If user is admin, send admin commands in DM
    if ctx.author.id == ADMIN_ID:
        admin_embed = discord.Embed(
            title="⚙️ Admin Commands",
            description="These commands are only available to you.",
            color=COLORS["primary"])
        admin_embed.add_field(name="Admin Tools",
                              value="\n".join([
                                  f"`{cmd}` - {desc}"
                                  for cmd, desc in admin_commands.items()
                              ]),
                              inline=False)

        try:
            await ctx.author.send(embed=admin_embed)
        except discord.Forbidden:
            await ctx.send(
                f"⚠️ {ctx.author.mention}, I couldn't send you the admin commands. Check your privacy settings.",
                delete_after=10)


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


@bot.command(name="alllogs", help="View all users' logs (Admin only)")
@admin_only()
@commands.has_permissions(administrator=True)
async def alllogs(ctx):
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

    messages = []
    for user_id, dates in logs.items():
        member = guild.get_member(int(user_id))
        name = member.display_name if member else f"User ID {user_id}"
        entry_lines = [f"**{name}** (`{user_id}`):"]

        for date, logs_list in sorted(dates.items()):
            entry_lines.append(f"  - {date}:")
            for log_entry in logs_list:
                if isinstance(log_entry, dict):
                    ts = log_entry.get("timestamp", "unknown time")
                    log_text = log_entry.get("log", "")
                    entry_lines.append(f"    • [{ts}] {log_text}")
                else:
                    entry_lines.append(f"    • {log_entry}")

        messages.append("\n".join(entry_lines))

    # Chunk and DM to admin
    chunk_size = 1900
    chunks = []
    current_chunk = ""
    for msg in messages:
        if len(current_chunk) + len(msg) + 2 > chunk_size:
            chunks.append(current_chunk)
            current_chunk = ""
        current_chunk += msg + "\n\n"

    if current_chunk:
        chunks.append(current_chunk)

    for chunk in chunks:
        await ctx.author.send(f"📋 All Logs:\n{chunk}")


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
    user_logs[user_id][date_str][-1]["timestamp"] = datetime.utcnow(
    ).isoformat()
    save_logs(user_logs)

    await ctx.send(f"✅ Updated your last log on `{date_str}` to:\n`{new_desc}`"
                   )

    # Delete user message for cleanliness
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="log", help="Log your daily work")
async def log(ctx, *, message: str):
    try:
        print(f"[DEBUG] log triggered with: {message}")

        # Remove surrounding quotes if present
        if message.startswith('"') and message.endswith('"'):
            message = message[1:-1]

        user_id = str(ctx.author.id)
        today = str(datetime.now(EST).date())

        logs = load_logs()

        if user_id not in logs:
            logs[user_id] = {}

        if today not in logs[user_id]:
            logs[user_id][today] = []
        elif isinstance(logs[user_id][today], str):
            # Convert legacy string log to list format
            logs[user_id][today] = [{
                "timestamp": "converted",
                "log": logs[user_id][today]
            }]

        logs[user_id][today].append({
            "timestamp": datetime.now(EST).isoformat(),
            "log": message
        })

        save_logs(logs)

        try:
            await ctx.author.send(f"✅ Your log has been saved:\n`{message}`")
        except discord.Forbidden:
            await ctx.send("✅ Log saved, but I couldn't DM you.")

        embed = discord.Embed(
            title="✅ Log Saved",
            description=f"Your work for {today} has been recorded!",
            color=COLORS["success"])
        await ctx.send(embed=embed)

        try:
            await ctx.message.delete()
        except discord.Forbidden:
            print("[WARN] Couldn't delete user message – missing permissions?")

    except Exception as e:
        error_embed = discord.Embed(title="❌ Command Error",
                                    description=f"An error occurred: {e}",
                                    color=COLORS["error"])
        await ctx.send(embed=error_embed)


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
    """Add a new task with standard date format (YYYY-MM-DD) and optional priority"""
    if not args:
        embed = create_error_embed(
            "Invalid Format",
            "Usage: `!addtask \"description\" [due_date] [priority]`\n"
            "• Date must be in format `YYYY-MM-DD`\n"
            "• Priority can be `low`, `normal`, or `high`")
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

    for token in remaining:
        if token.lower() in {"low", "normal", "high"}:
            priority = token.lower()
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
    embed.set_footer(text=f"Created by {ctx.author.display_name}")

    await ctx.send(embed=embed)


@bot.command(name="assign",
             help="Assign task to member: !assign @member <task ID>")
@admin_only()
@is_admin()
async def assign_task(ctx, member: discord.Member, task_id: int):
    task_found = None
    for creator_id, tasks in bot.user_tasks_created.items():
        if task_id in tasks:
            task_found = tasks[task_id]
            break

    if not task_found:
        embed = create_error_embed("Not Found", "Task ID not found.")
        return await ctx.send(embed=embed)

    if member.id not in bot.task_assignments:
        bot.task_assignments[member.id] = {}

    bot.task_assignments[member.id][task_id] = dict(task_found)
    bot.task_assignments[member.id][task_id]["status"] = "Pending"
    bot.task_assignments[member.id][task_id]["assigned_to"] = member.id
    save_tasks(bot.task_assignments)

    due_str = f", due by {task_found['due_date']}" if task_found[
        'due_date'] else ""

    embed = discord.Embed(
        title="📌 Task Assigned",
        description=
        f"Task #{task_id} has been assigned to {member.display_name}",
        color=COLORS["success"])
    embed.add_field(name="Description",
                    value=task_found['description'],
                    inline=False)
    embed.add_field(name="Due Date",
                    value=task_found.get('due_date', 'Not specified'),
                    inline=True)
    embed.add_field(name="Priority",
                    value=task_found.get('priority', 'Normal').capitalize(),
                    inline=True)

    await ctx.send(embed=embed)


@bot.command(name="mytasks", help="View your assigned tasks")
async def my_tasks(ctx):
    user_tasks = bot.task_assignments.get(ctx.author.id, {})
    if not user_tasks:
        embed = create_info_embed("No Tasks", "You have no assigned tasks.")
        return await ctx.send(embed=embed)

    embed = discord.Embed(title=f"📋 Your Tasks ({len(user_tasks)})",
                          color=COLORS["primary"])

    for tid, task in user_tasks.items():
        status_emoji = "✅" if task.get("status") == "Completed" else "⏳"
        due_date = task.get("due_date", "No due date")
        embed.add_field(
            name=
            f"{status_emoji} Task #{tid} - {task.get('priority', 'Normal').capitalize()}",
            value=f"**{task.get('description')}**\nDue: {due_date}",
            inline=False)

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


@bot.command(name="updatetask")
async def update_task(ctx, *, args=None):
    if not args:
        embed = create_error_embed(
            "Invalid Format",
            "Usage: `!updatetask <task_id> \"new description\" [YYYY-MM-DD] [priority]`\n"
            "Priority can be low, normal, or high.")
        return await ctx.send(embed=embed)

    import re
    from datetime import datetime

    # Match: task_id "description" [optional date] [optional priority]
    pattern = r'^(\d+)\s+"([^"]+)"(?:\s+(\d{4}-\d{2}-\d{2}))?(?:\s+(low|normal|high))?$'
    match = re.match(pattern, args.strip(), re.IGNORECASE)

    if not match:
        embed = create_error_embed(
            "Invalid Format",
            "Usage: `!updatetask <task_id> \"new description\" [YYYY-MM-DD] [priority]`"
        )
        return await ctx.send(embed=embed)

    task_id_str, new_desc, due_date_str, priority = match.groups()
    task_id = int(task_id_str)
    priority = priority.lower() if priority else "normal"

    # Parse the due date
    if due_date_str:
        try:
            due = datetime.strptime(due_date_str, "%Y-%m-%d")
            due_iso = due.isoformat(
            )  # Save in ISO format like 2025-05-25T00:00:00
        except ValueError:
            embed = create_error_embed("Invalid Date",
                                       "Please use YYYY-MM-DD format.")
            return await ctx.send(embed=embed)
    else:
        due_iso = None

    # Update in tasks the user created
    for creator_id, tasks in bot.user_tasks_created.items():
        if task_id in tasks:
            tasks[task_id]['description'] = new_desc
            tasks[task_id]['due_date'] = due_iso
            tasks[task_id]['priority'] = priority

            embed = discord.Embed(title=f"✅ Task #{task_id} Updated",
                                  color=COLORS["success"])
            embed.add_field(name="Description", value=new_desc, inline=False)
            embed.add_field(name="Due Date",
                            value=due_iso or "Not specified",
                            inline=True)
            embed.add_field(name="Priority",
                            value=priority.capitalize(),
                            inline=True)

            return await ctx.send(embed=embed)

    # Update in tasks assigned to the user
    for assignee_id, tasks in bot.task_assignments.items():
        if task_id in tasks:
            tasks[task_id]['description'] = new_desc
            tasks[task_id]['due_date'] = due_iso
            tasks[task_id]['priority'] = priority

            save_tasks(bot.task_assignments)  # Don't forget to persist

            embed = discord.Embed(title=f"✅ Task #{task_id} Updated",
                                  color=COLORS["success"])
            embed.add_field(name="Description", value=new_desc, inline=False)
            embed.add_field(name="Due Date",
                            value=due_iso or "Not specified",
                            inline=True)
            embed.add_field(name="Priority",
                            value=priority.capitalize(),
                            inline=True)

            return await ctx.send(embed=embed)

    # If task wasn't found
    embed = create_error_embed("Not Found",
                               f"Task ID {task_id} not found in your tasks.")
    await ctx.send(embed=embed)


@bot.command(name="commenttask",
             help="Add comment to a task: !commenttask <task ID> <comment>")
async def comment_task(ctx, task_id: int, *, comment: str):
    user_tasks = bot.task_assignments.get(ctx.author.id, {})
    if task_id not in user_tasks:
        embed = create_error_embed("Not Found",
                                   "Task ID not found in your assignments.")
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


@bot.command(name="health", help="View your daily logs in a beautiful format")
async def health(ctx, member: discord.Member = None):
    member = member or ctx.author

    # Permission check
    if member != ctx.author and ctx.author.id != ADMIN_ID:
        embed = discord.Embed(
            title="⛔ ACCESS DENIED",
            description=f"You can't view {member.display_name}'s logs",
            color=COLORS["error"])
        return await ctx.send(embed=embed, delete_after=10)

    logs = load_logs()
    user_logs = logs.get(str(member.id), {})

    if not user_logs:
        embed = discord.Embed(
            title="📭 NO LOGS FOUND",
            description=f"{member.display_name} hasn't logged anything yet!",
            color=COLORS["warning"])
        # Add the log button to empty state
        view = LogButton()
        return await ctx.send(embed=embed, view=view)

    # Create paginated view with the button
    view = HealthLogsView(member.id, user_logs)
    embed = view.create_embed()

    # Add the log button to the view
    view.add_item(
        Button(label="➕ Add New Log",
               style=discord.ButtonStyle.green,
               custom_id="add_log_button"))

    await ctx.send(embed=embed, view=view)


@bot.command(name="viewlogs",
             help="View your logs or another user's logs (admin only)")
async def view_logs(ctx, member: discord.Member = None):
    logs = load_logs()

    # Determine whose logs to view
    target = member or ctx.author
    is_admin = ctx.author.id == ADMIN_ID

    if target != ctx.author and not is_admin:
        return await ctx.send(
            "⛔ You don't have permission to view others' logs.")

    user_logs = logs.get(str(target.id), {})
    if not user_logs:
        return await ctx.send("📭 No logs found.")

    # Flatten logs into list of entries with date + log
    entries = []
    for date, log_list in sorted(user_logs.items(), reverse=True):
        # Normalize log_list into a list of dicts
        if isinstance(log_list, str):
            log_list = [{"timestamp": "converted", "log": log_list}]
        elif isinstance(log_list, dict):
            log_list = [log_list]
        elif isinstance(log_list, list):
            new_list = []
            for entry in log_list:
                if isinstance(entry, str):
                    new_list.append({"timestamp": "converted", "log": entry})
                elif isinstance(entry, dict):
                    new_list.append(entry)
            log_list = new_list
        else:
            log_list = []

        for log in log_list:
            entries.append({"date": date, "log": log["log"]})

    if not entries:
        return await ctx.send("📭 No logs found.")

    view = SingleLogPaginatedView(target, entries)
    embed = view.create_embed()
    return await ctx.send(embed=embed, view=view)


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


@bot.command(name="completetask",
             help="Mark a task as completed: !completetask <task ID>")
async def complete_task(ctx, task_id: int):
    user_tasks = bot.task_assignments.get(ctx.author.id, {})
    if task_id not in user_tasks:
        embed = create_error_embed("Not Found",
                                   "Task ID not found in your assignments.")
        return await ctx.send(embed=embed)

    task = user_tasks[task_id]
    task["status"] = "Completed"
    task["completed_at"] = str(datetime.now(EST))
    save_tasks(bot.task_assignments)

    # Update user score (gamification)
    bot.user_scores[ctx.author.id] = bot.user_scores.get(ctx.author.id, 0) + 10

    embed = create_success_embed(
        "Task Completed",
        f"Task #{task_id} marked as completed!\n+10 points! Your total score: {bot.user_scores[ctx.author.id]}"
    )
    await ctx.send(embed=embed)


# 2. Gamification Leaderboard
@bot.command(name="leaderboard",
             aliases=["lb"],
             help="Show the top contributors")
async def leaderboard(ctx):
    if not bot.user_scores:
        embed = create_info_embed(
            "Leaderboard", "No scores yet! Complete tasks to earn points.")
        return await ctx.send(embed=embed)

    sorted_scores = sorted(bot.user_scores.items(),
                           key=lambda x: x[1],
                           reverse=True)

    embed = discord.Embed(
        title="🏆 Leaderboard",
        description="Top contributors based on completed tasks",
        color=COLORS["neutral"])

    for rank, (user_id, score) in enumerate(sorted_scores[:10], 1):
        user = ctx.guild.get_member(user_id)
        if user:
            embed.add_field(name=f"{rank}. {user.display_name}",
                            value=f"🔹 {score} points",
                            inline=False)

    embed.set_thumbnail(url="https://i.imgur.com/Vk9KJ1B.png")
    await ctx.send(embed=embed)


# 3. Task Search Functionality
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


# 5. Weekly Summary
@tasks.loop(time=time(18, 0))  # Runs at midnight on Sunday
async def weekly_summary():
    await bot.wait_until_ready()

    # Only run on Sundays
    if datetime.now(EST).weekday() != 6:  # Sunday is 6
        return

    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        return

    logs = load_logs()
    if not logs:
        return

    embed = discord.Embed(title="📊 Weekly Summary",
                          description="Here's the weekly activity report",
                          color=COLORS["neutral"],
                          timestamp=datetime.now(EST))

    # Count logs per user
    user_log_counts = {uid: len(user_logs) for uid, user_logs in logs.items()}
    sorted_users = sorted(user_log_counts.items(),
                          key=lambda x: x[1],
                          reverse=True)

    # Add top contributors
    if sorted_users:
        embed.add_field(name="🏆 Top Contributors",
                        value="\n".join(f"<@{uid}>: {count} logs"
                                        for uid, count in sorted_users[:3]),
                        inline=False)

    # Add task completion stats
    completed_tasks = sum(1 for user_tasks in bot.task_assignments.values()
                          for task in user_tasks.values()
                          if task.get("status") == "Completed")
    embed.add_field(name="✅ Completed Tasks",
                    value=f"{completed_tasks} tasks completed this week",
                    inline=True)

    embed.set_footer(text="Great work everyone! Keep it up!")
    await channel.send(embed=embed)


# 6. User Profile Command
@bot.command(name="profile", help="View your profile and stats")
async def user_profile(ctx, member: discord.Member = None):
    member = member or ctx.author

    # Check permissions if viewing someone else's profile
    if member != ctx.author and ctx.author.id != ADMIN_ID:
        embed = create_error_embed(
            "Permission Denied",
            "You can only view your own profile unless you're an admin")
        return await ctx.send(embed=embed)

    logs = load_logs()
    user_logs = logs.get(str(member.id), {})

    embed = discord.Embed(title=f"👤 {member.display_name}'s Profile",
                          color=COLORS["primary"],
                          timestamp=datetime.now(EST))

    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)

    # Basic info
    embed.add_field(name="Member Since",
                    value=member.joined_at.strftime("%B %d, %Y"),
                    inline=True)

    # Log stats
    embed.add_field(name="Log Entries",
                    value=f"{len(user_logs)} this week",
                    inline=True)

    # Task stats
    assigned_tasks = len(bot.task_assignments.get(member.id, {}))
    completed_tasks = sum(
        1 for task in bot.task_assignments.get(member.id, {}).values()
        if task.get("status") == "Completed")
    embed.add_field(
        name="Tasks",
        value=f"Assigned: {assigned_tasks}\nCompleted: {completed_tasks}",
        inline=True)

    # Score if available
    if member.id in bot.user_scores:
        embed.add_field(name="Score",
                        value=f"🏅 {bot.user_scores[member.id]} points",
                        inline=True)

    await ctx.send(embed=embed)


from datetime import datetime


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


# 10. Task Reminder Configuration
@bot.command(name="taskreminders", help="Configure your task reminders")
async def task_reminders(ctx, frequency: str = None):
    if not frequency:
        # Show current settings
        embed = create_info_embed(
            "Task Reminders", "Current reminder settings: Daily at 6PM UTC\n"
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
            "You'll receive daily task reminders at 6PM UTC.")
    elif frequency == "weekly":
        # Enable weekly reminders
        embed = create_success_embed(
            "Weekly Reminders",
            "You'll receive weekly task reminders on Mondays at 10AM UTC.")
    else:
        embed = create_error_embed("Invalid Option",
                                   "Please use: off, daily, or weekly")

    await ctx.send(embed=embed)

    # ========== Startup ==========


if __name__ == "__main__":
    # Load additional data
    try:
        with open("scores.json", "r") as f:
            bot.user_scores = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        bot.user_scores = {}

bot.run(TOKEN)

