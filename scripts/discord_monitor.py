import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
from datetime import datetime, timezone
from supabase import create_client, Client

# Load .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
STAGE_CHANNEL_ID = int(os.getenv("STAGE_CHANNEL_ID"))
SUPABASE_URL = os.getenv("DISCORD_SUPABASE_URL")
SUPABASE_KEY = os.getenv("DISCORD_SUPABASE_KEY")

# Get meeting name from user input
MEETING_NAME = input("Enter meeting name: ").strip()

# Initialize Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Intents
intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True  

bot = commands.Bot(command_prefix="!", intents=intents)

# Attendance storage
# {user_id: {"join": datetime, "total_seconds": int}}
attendance = {}

def format_duration(seconds):
    """Convert seconds to readable format like 20s, 1h 28m 8s"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"

def parse_duration(duration_str):
    """Parse duration string back to seconds"""
    if isinstance(duration_str, int):
        return duration_str
    
    total_seconds = 0
    parts = duration_str.split()
    
    for part in parts:
        if part.endswith('h'):
            total_seconds += int(part[:-1]) * 3600
        elif part.endswith('m'):
            total_seconds += int(part[:-1]) * 60
        elif part.endswith('s'):
            total_seconds += int(part[:-1])
    
    return total_seconds

# Utility function to ensure datetime is timezone-aware
def to_aware(dt):
    """Normalize a datetime to timezone-aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")
    print(f"Monitoring stage channel ID: {STAGE_CHANNEL_ID}")
    
    # Join stage as audience
    stage_channel = bot.get_channel(STAGE_CHANNEL_ID)
    if stage_channel and isinstance(stage_channel, discord.StageChannel):
        try:
            # Check if any members are already in the stage channel and track their join time
            for member in stage_channel.members:
                if member == bot.user or member.bot:
                    continue

                voice_state = member.voice
                if voice_state and voice_state.channel and voice_state.channel.id == STAGE_CHANNEL_ID:
                    join_time = to_aware(voice_state.joined_at) or datetime.now(timezone.utc)
                    attendance[member.id] = attendance.get(member.id, {"total_seconds": 0})
                    attendance[member.id]["join"] = join_time
                    print(f"{member.display_name} was already in stage since {join_time} — tracking from existing join time")

            # Connect to stage channel
            voice_client = await stage_channel.connect()
            # Request to speak (join as audience)
            await stage_channel.guild.me.edit(suppress=True)
            print(f"Joined stage channel as audience: {stage_channel.name}")
        except Exception as e:
            print(f"Failed to join stage: {e}")
    else:
        print("Stage channel not found or not a stage channel")

@bot.event
async def on_voice_state_update(member, before, after):
    # Skip bot's own voice state changes
    if member == bot.user:
        return
        
    # Joined stage
    if after.channel and after.channel.id == STAGE_CHANNEL_ID and (not before.channel or before.channel.id != STAGE_CHANNEL_ID):
        attendance[member.id] = attendance.get(member.id, {"total_seconds": 0})
        attendance[member.id]["join"] = datetime.now()
        print(f"{member.display_name} joined the stage at {attendance[member.id]['join']}")

    # Left stage
    if before.channel and before.channel.id == STAGE_CHANNEL_ID and (not after.channel or after.channel.id != STAGE_CHANNEL_ID):
        if member.id in attendance and "join" in attendance[member.id]:
            join_time = attendance[member.id].pop("join")
            duration = (datetime.now() - join_time).total_seconds()
            attendance[member.id]["total_seconds"] += int(duration)
            print(f"{member.display_name} left the stage. Duration: {int(duration)} seconds")
            
            # Save to Supabase - check if record exists first
            try:
                # Check if record exists
                existing = supabase.table("attendance").select("*").eq("display_name", member.display_name).eq("meeting_name", MEETING_NAME).execute()
                
                if existing.data:
                    # Update existing record
                    current_duration_seconds = parse_duration(existing.data[0]["duration"])
                    new_duration_seconds = current_duration_seconds + int(duration)
                    formatted_duration = format_duration(new_duration_seconds)
                    supabase.table("attendance").update({"duration": formatted_duration}).eq("display_name", member.display_name).eq("meeting_name", MEETING_NAME).execute()
                    print(f"Updated {member.display_name}'s total duration to {formatted_duration}")
                else:
                    # Insert new record
                    formatted_duration = format_duration(int(duration))
                    supabase.table("attendance").insert({
                        "display_name": member.display_name,
                        "username": member.name,
                        "duration": formatted_duration,
                        "meeting_name": MEETING_NAME
                    }).execute()
                    print(f"Created new record for {member.display_name} with {formatted_duration}")
            except Exception as e:
                print(f"Failed to save to database: {e}")

async def main():
    print(f"Bot starting... Meeting: {MEETING_NAME}")
    await bot.start(TOKEN)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
