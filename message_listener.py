from telethon import events
from models.models import get_session, Chat, ForwardRule
import logging
from handlers import user_handler, bot_handler
from handlers.prompt_handlers import handle_prompt_setting
import asyncio
import os
from dotenv import load_dotenv
from telethon.tl.types import ChannelParticipantsAdmins
from managers.state_manager import state_manager
from telethon.tl import types
from filters.process import process_forward_rule
# Load environment variables
load_dotenv()

# Get logger
logger = logging.getLogger(__name__)

# Add a cache to store processed media groups
PROCESSED_GROUPS = set()

BOT_ID = None

async def setup_listeners(user_client, bot_client):
    """
    Setting up a message listener
    
    Args:
        user_client: User client (used for monitoring messages and forwarding)
        bot_client: robot client (for processing commands and forwarding)
    """
    global BOT_ID
    
    # Get the robot ID directly
    try:
        me = await bot_client.get_me()
        BOT_ID = me.id
        logger.info(f"Get robot ID: {BOT_ID} (type: {type(BOT_ID)})")
    except Exception as e:
        logger.error(f"Error getting robot ID: {str(e)}")
    
    # Filter to exclude the robot's own messages
    async def not_from_bot(event):
        if BOT_ID is None:
            return True # If the robot ID is not obtained, no filtering is performed
        
        sender = event.sender_id
        try:
            sender_id = int(sender) if sender is not None else None
            is_not_bot = sender_id != BOT_ID
            if not is_not_bot:
                logger.info(f"Filter recognizes robot message, ignores processing: {sender_id}")
            return is_not_bot
        except (ValueError, TypeError):
            return True # No filtering when conversion fails
    
    # User client listener - use filters to avoid processing robot messages
    @user_client.on(events.NewMessage(func=not_from_bot))
    async def user_message_handler(event):
        await handle_user_message(event, user_client, bot_client)
    
    # Robot Client Listener - Using Filters
    @bot_client.on(events.NewMessage(func=not_from_bot))
    async def bot_message_handler(event):
        # logger.info(f"The robot received a message that was not sent to it, sender ID: {event.sender_id}")
        await handle_bot_message(event, bot_client)
        
    # Register robot callback handler
    bot_client.add_event_handler(bot_handler.callback_handler)

async def handle_user_message(event, user_client, bot_client):
    """Process messages received by the user client"""
    # logger.info("handle_user_message: Start processing user messages")
    
    chat = await event.get_chat()
    chat_id = abs(chat.id)
    # logger.info(f"handle_user_message:Get the chat ID: {chat_id}")

    # Check if it is a channel message
    if isinstance(event.chat, types.Channel) and state_manager.check_state():
        # logger.info("handle_user_message: channel message detected and exists")
        sender_id = os.getenv('USER_ID')
        # The channel ID needs to be prefixed with 100
        chat_id = int(f"100{chat_id}")
        # logger.info(f"handle_user_message: channel message processing: sender_id={sender_id}, chat_id={chat_id}")
    else:
        sender_id = event.sender_id
        # logger.info(f"handle_user_message: non-channel message processing: sender_id={sender_id}")

    # Check user status
    current_state, message, state_type = state_manager.get_state(sender_id, chat_id)
    # logger.info(f'handle_user_message: Is there a current state: {state_manager.check_state()}')
    # logger.info(f"handle_user_message: current user ID and chat ID: {sender_id}, {chat_id}")
    # logger.info(f"handle_user_message: Get the user status of the current chat window: {current_state}")
    
    if current_state:
        # logger.info(f"User status detected: {current_state}")
        # Processing prompt word settings
        # logger.info("Prepare to process prompt word settings")
        if await handle_prompt_setting(event, bot_client, sender_id, chat_id, current_state, message):
            # logger.info("Prompt word setting processing completed, return")
            return
        # logger.info("Prompt word setting processing is not completed, continue to execute")

    # Check if it is a media group message
    if event.message.grouped_id:
        # If this media group has already been processed, skip it
        group_key = f"{chat_id}:{event.message.grouped_id}"
        if group_key in PROCESSED_GROUPS:
            return
        # Mark this media group as processed
        PROCESSED_GROUPS.add(group_key)
        asyncio.create_task(clear_group_cache(group_key))
    
    # First check if there is a forwarding rule for this chat in the database
    session = get_session()
    try:
        # Query source chat
        source_chat = session.query(Chat).filter(
            Chat.telegram_chat_id == str(chat_id)
        ).first()
        
        if not source_chat:
            return
            
        # Add log: query forwarding rules
        logger.info(f'Found source chat: {source_chat.name} (ID: {source_chat.id})')
        
        # Find rules with current chat as source
        rules = session.query(ForwardRule).filter(
            ForwardRule.source_chat_id == source_chat.id
        ).all()
        
        if not rules:
            logger.info(f'Chat {source_chat.name} has no forwarding rules')
            return
        
        # Only when there is a forwarding rule, the message information is recorded
        if event.message.grouped_id:
            logger.info(f'[user] Received media group message from chat: {source_chat.name} ({chat_id}) group id: {event.message.grouped_id}')
        else:
            logger.info(f'[user] Received new message from chat: {source_chat.name} ({chat_id}) content: {event.message.text}')
            
        # Add log: processing rules
        logger.info(f'Found {len(rules)} forwarding rules')
        
        # Process each forwarding rule
        for rule in rules:
            target_chat = rule.target_chat
            if not rule.enable_rule:
                logger.info(f'Rule {rule.id} is not enabled')
                continue
            logger.info(f'Processing forwarding rule ID: {rule.id} (forwarding from {source_chat.name} to: {target_chat.name})')
            if rule.use_bot:
                # Directly use the process_forward_rule function in the filter module
                await process_forward_rule(bot_client, event, str(chat_id), rule)
            else:
                await user_handler.process_forward_rule(user_client, event, str(chat_id), rule)
        
    except Exception as e:
        logger.error(f'An error occurred while processing user messages: {str(e)}')
        logger.exception(e) # add detailed error stack
    finally:
        session.close()

async def handle_bot_message(event, bot_client):
    """Process messages (commands) received by the robot client"""
    try:
            
        # logger.info("handle_bot_message: Start processing robot messages")
        
        chat = await event.get_chat()
        chat_id = abs(chat.id)
        # logger.info(f"handle_bot_message:Get chat ID: {chat_id}")

        # Check if it is a channel message
        if isinstance(event.chat, types.Channel) and state_manager.check_state():
            # logger.info("handle_bot_message: channel message detected and exists")
            sender_id = os.getenv('USER_ID')
            # The channel ID needs to be prefixed with 100
            chat_id = int(f"100{chat_id}")
            # logger.info(f"handle_bot_message: channel message processing: sender_id={sender_id}, chat_id={chat_id}")
        else:
            sender_id = event.sender_id
            # logger.info(f"handle_bot_message: non-channel message processing: sender_id={sender_id}")

        # Check user status
        current_state, message, state_type = state_manager.get_state(sender_id, chat_id)
        # logger.info(f'handle_bot_message: Is there a current state: {state_manager.check_state()}')
        # logger.info(f"handle_bot_message: current user ID and chat ID: {sender_id}, {chat_id}")
        # logger.info(f"handle_bot_message: Get the user status of the current chat window: {current_state}")

        
        
        # Processing prompt word settings
        if current_state:
            await handle_prompt_setting(event, bot_client, sender_id, chat_id, current_state, message)
            return

        # If there is no special status, process regular commands
        await bot_handler.handle_command(bot_client, event)
    except Exception as e:
        logger.error(f'An error occurred while processing the robot command: {str(e)}')
        logger.exception(e)

async def clear_group_cache(group_key, delay=300): # Clear cache after 5 minutes
    """Clear processed media group records"""
    await asyncio.sleep(delay)
    PROCESSED_GROUPS.discard(group_key)

