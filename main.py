from telethon import TelegramClient, types
from telethon.tl.types import BotCommand
from telethon.tl.functions.bots import SetBotCommandsRequest
from models.models import init_db
from dotenv import load_dotenv
from message_listener import setup_listeners
import os
import asyncio
import logging
import uvicorn
import multiprocessing
from models.db_operations import DBOperations
from scheduler.summary_scheduler import SummaryScheduler
from scheduler.chat_updater import ChatUpdater
from handlers.bot_handler import send_welcome_message
from rss.main import app as rss_app
from utils.log_config import setup_logging

# Set the default configuration for Docker logs. If no log options are configured in docker-compose.yml, these values ​​will be used
os.environ.setdefault('DOCKER_LOG_MAX_SIZE', '10m')
os.environ.setdefault('DOCKER_LOG_MAX_FILE', '3')

# Set log configuration
setup_logging()

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Get configuration from environment variables
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
bot_token = os.getenv('BOT_TOKEN')
phone_number = os.getenv('PHONE_NUMBER')

# Create a DBOperations instance
db_ops = None

scheduler = None
chat_updater = None


async def init_db_ops():
    """Initialize the DBOperations instance"""
    global db_ops
    if db_ops is None:
        db_ops = await DBOperations.create()
    return db_ops


# Create folder
os.makedirs('./sessions', exist_ok=True)
os.makedirs('./temp', exist_ok=True)


# Clear the ./temp folder
def clear_temp_dir():
    for file in os.listdir('./temp'):
        os.remove(os.path.join('./temp', file))


# Create a client
user_client = TelegramClient('./sessions/user', api_id, api_hash)
bot_client = TelegramClient('./sessions/bot', api_id, api_hash)

# Initialize the database
engine = init_db()


def run_rss_server(host: str, port: int):
    """Run the RSS server in a new process"""
    uvicorn.run(
        rss_app,
        host=host,
        port=port
    )


async def start_clients():
    # Initialize DBOperations
    global db_ops, scheduler, chat_updater
    db_ops = await DBOperations.create()

    try:
        # Start the user client
        await user_client.start(phone=phone_number)
        me_user = await user_client.get_me()
        print(f'User client started: {me_user.first_name} (@{me_user.username})')

        # Start the robot client
        await bot_client.start(bot_token=bot_token)
        me_bot = await bot_client.get_me()
        print(f'The robot client has been started: {me_bot.first_name} (@{me_bot.username})')

        # Set up a message listener
        await setup_listeners(user_client, bot_client)

        # Register Command
        await register_bot_commands(bot_client)

        # Create and start the scheduler
        scheduler = SummaryScheduler(user_client, bot_client)
        await scheduler.start()
        
        # Create and start the chat message updater
        chat_updater = ChatUpdater(user_client)
        await chat_updater.start()

        # If RSS service is enabled
        if os.getenv('RSS_ENABLED', '').lower() == 'true':
            try:
                rss_host = os.getenv('RSS_HOST', '0.0.0.0')
                rss_port = int(os.getenv('RSS_PORT', '8000'))
                logger.info(f"Starting RSS service (host={rss_host}, port={rss_port})")
                
                # Start the RSS service in a new process
                rss_process = multiprocessing.Process(
                    target=run_rss_server,
                    args=(rss_host, rss_port)
                )
                rss_process.start()
                logger.info("RSS service started successfully")
            except Exception as e:
                logger.error(f"Failed to start RSS service: {str(e)}")
                logger.exception(e)
        else:
            logger.info("RSS service is not enabled")

        # Send a welcome message
        await send_welcome_message(bot_client)

        # Wait for both clients to disconnect
        await asyncio.gather(
            user_client.run_until_disconnected(),
            bot_client.run_until_disconnected()
        )
    finally:
        # Disable DBOperations
        if db_ops and hasattr(db_ops, 'close'):
            await db_ops.close()
        # Stop the scheduler
        if scheduler:
            scheduler.stop()
        # Stop the chat message updater
        if chat_updater:
            chat_updater.stop()
        # If the RSS service is running, stop it
        if 'rss_process' in locals() and rss_process.is_alive():
            rss_process.terminate()
            rss_process.join()


async def register_bot_commands(bot):
    """Register robot command"""
    # # Clear existing commands first
    # try:
    # await bot(SetBotCommandsRequest(
    # scope=types.BotCommandScopeDefault(),
    #lang_code='',
    # commands=[] # Empty list clears all commands
    # ))
    # logger.info('Existing robot commands have been cleared')
    # except Exception as e:
    # logger.error(f'Error clearing robot command: {str(e)}')

    commands = [
        # Basic commands
        BotCommand(
            command='start',
            description = 'Get started'
        ),
        BotCommand(
            command='help',
            description = 'View help'
        ),
        # Binding and Setup
        BotCommand(
            command='bind',
            description = 'Bound source chat'
        ),
        BotCommand(
            command='settings',
            description = 'Manage forwarding rules'
        ),
        BotCommand(
            command='switch',
            description='Switch the chat rules that need to be set currently'
        ),
        # Keyword Management
        BotCommand(
            command='add',
            description = 'Add keywords'
        ),
        BotCommand(
            command='add_regex',
            description = 'Add regular keywords'
        ),
        BotCommand(
            command='add_all',
            description = 'Add common keywords to all rules'
        ),
        BotCommand(
            command='add_regex_all',
            description = 'Add regular expression to all rules'
        ),
        BotCommand(
            command='list_keyword',
            description = 'List all keywords'
        ),
        BotCommand(
            command='remove_keyword',
            description = 'Delete keyword'
        ),
        BotCommand(
            command='remove_keyword_by_id',
            description = 'Delete keywords by ID'
        ),
        BotCommand(
            command='remove_all_keyword',
            description = 'Delete the specified keyword of all rules bound to the current channel'
        ),
        # Replacement rule management
        BotCommand(
            command='replace',
            description = 'Add replacement rules'
        ),
        BotCommand(
            command='replace_all',
            description = 'Add replacement rules to all rules'
        ),
        BotCommand(
            command='list_replace',
            description = 'List all replacement rules'
        ),
        BotCommand(
            command='remove_replace',
            description = 'Delete replacement rules'
        ),
        # Import and export functions
        BotCommand(
            command='export_keyword',
            description = 'Export keywords of the current rule'
        ),
        BotCommand(
            command='export_replace',
            description = 'Export replacement rules for the current rules'
        ),
        BotCommand(
            command='import_keyword',
            description = 'Import common keywords'
        ),
        BotCommand(
            command='import_regex_keyword',
            description = 'Import regular expression keywords'
        ),
        BotCommand(
            command='import_replace',
            description = 'Import replacement rules'
        ),
        # UFB related functions
        BotCommand(
            command='ufb_bind',
            description = 'Bind ufb domain name'
        ),
        BotCommand(
            command='ufb_unbind',
            description = 'Unbind ufb domain name'
        ),
        BotCommand(
            command = 'ufb_item_change',
            description = 'Switch ufb synchronization configuration type'
        ),
        BotCommand(
            command='clear_all_keywords',
            description = 'Clear all keywords of the current rule'
        ),
        BotCommand(
            command='clear_all_keywords_regex',
            description = 'Clear all regular keywords of the current rule'
        ),
        BotCommand(
            command='clear_all_replace',
            description = 'Clear all replacement rules for the current rule'
        ),
        BotCommand(
            command='copy_keywords',
            description = 'Copy the keyword of the parameter rule to the current rule'
        ),
        BotCommand(
            command='copy_keywords_regex',
            description = 'Copy the regular keyword of the parameter rule to the current rule'
        ),
        BotCommand(
            command='copy_replace',
            description = 'Copy the replacement rule of the parameter rule to the current rule'
        ),
        BotCommand(
            command='copy_rule',
            description = 'Copy parameter rules to current rules'
        ),
        BotCommand(
            command='changelog',
            description='View update log'
        ),
        BotCommand(
            command='list_rule',
            description = 'List all forwarding rules'
        ),
        BotCommand(
            command='delete_rule',
            description = 'Delete forwarding rules'
        ),
        BotCommand(
            command='delete_rss_user',
            description='Delete RSS User'
        ),


        # BotCommand(
        # command='clear_all',
        # description = 'Use with caution! Clear all data'
        # ),
    ]

    try:
        result = await bot(SetBotCommandsRequest(
            scope=types.BotCommandScopeDefault(),
            lang_code='', # Empty string means default language
            commands=commands
        ))
        if result:
            logger.info('Robot command successfully registered')
        else:
            logger.error('Registration robot command failed')
    except Exception as e:
        logger.error(f'Error registering robot command: {str(e)}')


if __name__ == '__main__':
    # Run the event loop
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start_clients())
    except KeyboardInterrupt:
        print("Closing client...")
    finally:
        loop.close()
