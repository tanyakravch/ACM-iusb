
import os
import logging
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.messages = True
intents.dm_messages = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# In-memory store for submissions (user_id -> answer)
submissions = {}
# Track users currently being prompted (to avoid duplicate waits)
pending_submissions = set()


@bot.event
async def on_ready():
    logger.info("✅ Logged in as %s", bot.user)
    try:
        synced = await bot.tree.sync()
        logger.info("🔧 Synced %d slash commands", len(synced))
    except Exception as e:
        logger.exception("❌ Error syncing commands")


@bot.tree.command(name="questionnaire", description="Answer this week's ACM question!")
async def questionnaire(interaction: discord.Interaction):
    user = interaction.user
    # Prevent double submissions
    if user.id in submissions:
        await interaction.response.send_message("⚠️ You have already submitted for this question.", ephemeral=True)
        return
    if user.id in pending_submissions:
        await interaction.response.send_message("⚠️ You already have a pending submission. Please reply to the prompt you were sent.", ephemeral=True)
        return

    # If the command is used in DMs (no guild), collect the answer in this channel
    if interaction.guild is None:
        try:
            # Acknowledge in the DM channel
            await interaction.response.send_message("Please reply to this message with your answer. This is your only chance.")
        except Exception:
            logger.exception("Failed to send DM acknowledgment in-channel")
            return

        # Mark pending and wait inline in the DM channel
        pending_submissions.add(user.id)
        try:
            def _check(m: discord.Message):
                return m.author.id == user.id and isinstance(m.channel, discord.DMChannel) and m.channel.id == interaction.channel.id

            logger.info("Waiting for inline DM reply from user %s in channel %s", user.id, interaction.channel.id)
            msg = await bot.wait_for("message", check=_check)
            answer = msg.content

            # Record and log
            submissions[user.id] = answer
            logger.info("Recorded submission for user %s (DM inline)", user.id)
            try:
                LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "1424285108231471194"))
                channel = bot.get_channel(LOG_CHANNEL_ID) or await bot.fetch_channel(LOG_CHANNEL_ID)
                await channel.send(f"📝 **New Submission!**\n👤 From: {user.mention}\n💬 Answer: {answer}")
            except Exception:
                logger.exception("Failed to log submission to channel from inline DM; saved locally")

            try:
                await user.send("✅ Thanks! Your answer has been submitted.")
            except Exception:
                logger.exception("Failed to DM user confirmation after inline submission")

        finally:
            pending_submissions.discard(user.id)
        return

    # Otherwise (invoked in a guild), acknowledge quickly then run background DM flow
    try:
        await interaction.response.send_message(
            "📬 Check your DMs to answer this week's question!",
            ephemeral=True,
        )
    except Exception:
        logger.exception("Failed to send initial ephemeral response")
        return

    # Schedule the DM flow in background. The task will handle its own errors
    # and notify the user in DM or via followup when appropriate.
    bot.loop.create_task(_handle_dm_questionnaire(interaction, user))


async def _handle_dm_questionnaire(interaction: discord.Interaction, user: discord.User):
    """Background task to DM the user, wait for their first reply, record it,
    and log it — isolating errors from the slash-command context.
    """
    LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "1424285108231471194"))
    try:
        # Send DM prompt
        try:
            logger.info("Attempting to send DM to user %s (%s)", user, user.id)
            dm = await user.send(
                """Hey there! Let's do this week's ACM question challenge 🎉

Please reply to this DM with your answer. This is your only chance to submit.

What is the output of ord('a') - ord('A') in Python?
"""

            )
            logger.info("DM sent to user %s", user.id)
        except discord.Forbidden:
            logger.warning("Cannot DM user %s (Forbidden)", user.id)
            # Can't DM the user; inform them via ephemeral followup
            try:
                await interaction.followup.send(
                    "⚠️ I can’t DM you — please enable DMs from server members.",
                    ephemeral=True,
                )
            except Exception:
                logger.exception("Failed to send followup after Forbidden in background task")
            return

        # Wait for DM reply
        def _check(m: discord.Message):
            return m.author.id == user.id and isinstance(m.channel, discord.DMChannel)

        logger.info("Waiting for DM reply from user %s", user.id)
        msg = await bot.wait_for("message", check=_check)
        logger.info("Received DM from user %s", user.id)
        answer = msg.content

        # If user already submitted, inform and return
        if user.id in submissions:
            try:
                await user.send("⚠️ You have already submitted. Further messages won't be recorded.")
            except Exception:
                logger.exception("Failed to DM user about duplicate submission")
            return

        # Record submission
        submissions[user.id] = answer
        logger.info("Recorded submission for user %s", user.id)

        # Try to log to channel; failures are logged but won't affect the user
        try:
            logger.info("Attempting to log submission for user %s to channel %s", user.id, LOG_CHANNEL_ID)
            channel = bot.get_channel(LOG_CHANNEL_ID)
            if channel is None:
                channel = await bot.fetch_channel(LOG_CHANNEL_ID)
            await channel.send(f"📝 **New Submission!**\n👤 From: {user.mention}\n💬 Answer: {answer}")
            logger.info("Logged submission for user %s to channel %s", user.id, LOG_CHANNEL_ID)
        except Exception:
            logger.exception("Failed to log submission to channel; submission saved locally")

        # DM confirmation
        try:
            await user.send("✅ Thanks! Your answer has been submitted.")
            logger.info("Sent confirmation DM to user %s", user.id)
        except Exception:
            logger.exception("Failed to DM user confirmation in background task")

    except Exception:
        # Any unexpected error should be logged; avoid sending the original
        # slash-command generic followup here because we're running in the
        # background and already acknowledged the interaction above.
        logger.exception("Unhandled error in background DM questionnaire task")


def _get_token():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN not set in environment. Create a .env file or set the variable.")
    return token


if __name__ == "__main__":
    token = _get_token()
    if token:
        bot.run(token)
    else:
        logger.error("Bot not started because DISCORD_TOKEN is missing.")
