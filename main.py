# main.py
import nextcord
from nextcord.ext import commands
import openai
from openai import AsyncOpenAI # <-- Import the new client
import os
import json
import asyncio
import dotenv
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """
You are the "Server Architect", a helper that helps users design a new Discord server.
Your goal is to have a natural conversation with the user to gather their information on what they are looking for and then generate a single JSON object that contains the server structure.

Your process:
1.  The user will provide an initial, general idea for their server.
2.  Based on their idea, you will ask for the specific details you need:
    - The server's name.
    - The names of any roles they want.
    - The names of categories and the channels within them (specifying if each channel is 'text' or 'voice').
3.  Be conversational. If the user provides some details upfront, acknowledge them and ask for what's missing. You don't have to ask for everything in a specific order.
4.  Once you are confident you have all the information required to make the server (server name, at least one role, and at least one category with a channel), and the user states they think its good, do a final review with the user.
5.  After the user confirms that everything looks good, your FINAL and ONLY response must be the complete JSON object, enclosed in a ```json ... ``` code block. Do not include any other text, greetings, or explanations in that final message as this will be used to trigger a function in the program.

**JSON Structure to follow:**
{
  "server_name": "Example Server Name",
  "roles": [
    {"name": "Admin"},
    {"name": "Moderator"},
    {"name": "Member"}
  ],
  "categories": [
    {
      "name": "General",
      "channels": [
        {"name": "welcome", "type": "text"},
        {"name": "announcements", "type": "text"}
      ]
    },
    {
      "name": "Voice Chats",
      "channels": [
        {"name": "Lobby", "type": "voice"},
        {"name": "Gaming", "type": "voice"}
      ]
    }
  ]
}
"""


intents = nextcord.Intents.default()
intents.message_content = True
intents.guilds = True  

bot = commands.Bot(command_prefix="!", intents=intents)

# A dictionary to keep track of conversations with users.
# Key: user.id, Value: dictionary containing the message history for OpenAI and the guild_id.
user_conversations = {}

# ================================================= ------------------ =================================================
# ================================================= --- BOT EVENTS --- =================================================
# ================================================= ------------------ =================================================

@bot.event
async def on_ready():
    print('---------------------------')
    print(f'Logged in as {bot.user}!')
    print('Bot is ready to receive DMs and slash commands.')
    print('---------------------------')
    print('\n\n')


# An event that is triggered on every message.
@bot.event
async def on_message(message: nextcord.Message):

    # Ignores messages from itself or messages that are not in DMs.
    if message.author == bot.user or not isinstance(message.channel, nextcord.DMChannel):
        return

    user_id = message.author.id
    user_message = message.content

    # Checks to see that the messages from the user are from a user that has a conversation started.
    if user_id in user_conversations:
        async with message.channel.typing():
            # Adds the user's last message to the message history.
            user_conversations[user_id]["messages"].append({"role": "user", "content": user_message})

            try:
                # Gets a response from the OpenAI API.
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=user_conversations[user_id]["messages"],
                    temperature=0.7,
                )
                # Access the response content.
                ai_response_text = response.choices[0].message.content

                # Adds the AI's response to the message history.
                user_conversations[user_id]["messages"].append({"role": "assistant", "content": ai_response_text})

                # Checks to see if the AI's response contains the final JSON.
                if "```json" in ai_response_text:
                    guild_id = user_conversations[user_id].get("guild_id")
                    await handle_json_and_create_server(message, ai_response_text, guild_id)
                    # Cleans up the conversation history after completion.
                    del user_conversations[user_id]
                else:
                    # If the message is just a regular conversational message, sends it to the user.
                    await message.channel.send(ai_response_text)

            except Exception as e:
                print(f"An error occurred with the OpenAI API: {e}")
                await message.channel.send("Sorry, I'm having a little trouble connecting to my brain right now. Please try again in a moment.")
                if user_id in user_conversations:
                    del user_conversations[user_id]

# ================================================= -------------------- =================================================
# ================================================= --- BOT COMMANDS --- =================================================
# ================================================= -------------------- =================================================

# A command that is triggered by using "/start" in the server that will be redone.
@bot.slash_command(name="start", description="Start configuring this Discord server. Will begin a chat in your DM's")
async def start_command(interaction: nextcord.Interaction):

    user_id = interaction.user.id

    # Checks to see that the user is an admin.
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "Sorry, you must be a server administrator to use this command.",
            ephemeral=True
        )
        return

    # Checks to see if a convsersation has already been started with the user.
    if user_id in user_conversations:
        await interaction.response.send_message(
            "You already have a server configuration process in progress in your DMs!",
            ephemeral=True
        )
        return

    # Starts a new conversation for this user, storing the guild ID.
    user_conversations[user_id] = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
        ],
        "guild_id": interaction.guild.id
    }

    # Sends a message in the server to confirm to the user that the command was executed.
    await interaction.response.send_message(
        f"I've sent you a DM to get started on re-configuring the '{interaction.guild.name}' server!",
        ephemeral=True
    )

    # Start the conversation in the user's DMs.
    try:
        dm_channel = await interaction.user.create_dm()
        await dm_channel.send("Greetings! I am the Server Architect and am ready to help you create your dream server. Please tell me what you are looking to make and we will go from there.")

    except nextcord.Forbidden:
        # This happens if the user has DMs disabled.
        await interaction.followup.send(
            "I couldn't send you a DM. Please enable your Direct Messages for this server to continue.",
            ephemeral=True
        )

        # Clean up the conversation since we can't proceed.
        if user_id in user_conversations:
            del user_conversations[user_id]
            
    except Exception as e:
        print(f"An error occurred during conversation initiation: {e}")
        await interaction.followup.send("An unexpected error occurred while trying to start our conversation.", ephemeral=True)
        if user_id in user_conversations:
            del user_conversations[user_id]

# ================================================= ----------------- =================================================
# ================================================= --- FUNCTIONS --- =================================================
# ================================================= ----------------- =================================================

# Extracts the JSON object from the AI's response and starts the server configuration process.
async def handle_json_and_create_server(message: nextcord.Message, ai_response: str, guild_id: int):

    # Checks to make sure the bot has access to the server
    try:
        guild = bot.get_guild(guild_id)
        _ = guild.name 
    except AttributeError:
        await message.channel.send("I can no longer see the server we were working on. Please make sure that I am in the server you want to re-build.")
        return

    await message.channel.send(f"Great! I have the final configuration. Please wait while I re-build the '{guild.name}' server. This might take a moment...")

    try:
        # Extracts the JSON string from the text response
        json_string = ai_response.split("```json\n")[1].split("\n```")[0]
        server_data = json.loads(json_string)

        # Calls the function to actually build the server
        await create_server_from_json(message.author, server_data, guild)

    except json.JSONDecodeError:
        await message.channel.send("There was an error in the JSON structure I generated. Could you please review our conversation and try summarizing the details again?")
        print("Error: Failed to decode JSON from AI response.")
    except IndexError:
        await message.channel.send("I seem to have formatted my final response incorrectly. Let's try that again. Can you confirm the details one last time?")
        print("Error: Failed to extract JSON from the markdown block.")
    except Exception as e:
        await message.channel.send(f"An unexpected error occurred during server creation: {e}")
        print(f"An unexpected error occurred: {e}")


# Wipes everything in the server and builds the new items listed in the JSON object
async def create_server_from_json(user: nextcord.User, data: dict, guild: nextcord.Guild):

    print(f"Starting server configuration for guild '{guild.name}' ({guild.id}) requested by {user.name}")

    try:
        # Renames the server
        server_name = data.get("server_name", guild.name)
        await guild.edit(name=server_name)

        # Deleting all channels
        print("Wiping existing channels...")
        for channel in await guild.fetch_channels():
            await channel.delete(reason="Server reconfiguration")
        
        # Deleting all roles except for default and integrated roles
        print("Wiping existing roles...")
        for role in guild.roles:
            if role.is_default() or role.is_integration():
                continue
            try:
                await role.delete(reason="Server reconfiguration")
            except nextcord.Forbidden:
                print(f"Could not delete role '{role.name}' - likely higher than bot's role.")


        # Creating new roles
        if "roles" in data and data["roles"]:
            for role_info in data["roles"]:
                role_name = role_info.get("name")
                if role_name and role_name != "@everyone":
                    try:
                        await guild.create_role(name=role_name)
                        print(f"Created role: {role_name} in {guild.name}")
                    except Exception as e:
                        print(f"Failed to create role {role_name}: {e}")

        # Creating New Channels
        if "categories" in data and data["categories"]:
            for category_info in data["categories"]:
                category_name = category_info.get("name")
                if not category_name: continue
                try:
                    new_category = await guild.create_category(name=category_name)
                    print(f"Created category: {category_name} in {guild.name}")
                    if "channels" in category_info and category_info["channels"]:
                        for channel_info in category_info["channels"]:
                            channel_name = channel_info.get("name")
                            channel_type = channel_info.get("type", "text").lower()
                            if not channel_name: continue
                            try:
                                if channel_type == "text":
                                    await guild.create_text_channel(name=channel_name, category=new_category)
                                elif channel_type == "voice":
                                    await guild.create_voice_channel(name=channel_name, category=new_category)
                                print(f"Created {channel_type} channel: {channel_name} in category {category_name}")
                            except Exception as e:
                                print(f"Failed to create channel {channel_name}: {e}")
                except Exception as e:
                    print(f"Failed to create category {category_name}: {e}")

        success_message = f"✅ Your server, '{guild.name}', has been reconfigured successfully!"
        await user.send(success_message)

    except nextcord.errors.HTTPException as e:
        error_message = f"A Discord API error occurred: {e.text}"
        print(error_message)
        await user.send(f"I'm sorry, but I ran into an error while configuring the server. Discord said: '{e.text}'. Please check my permissions and try again.")
    except Exception as e:
        error_message = f"An unexpected error occurred during server configuration: {e}"
        print(error_message)
        await user.send("I'm sorry, a critical and unexpected error occurred. I was unable to configure your server.")


if __name__ == "__main__":
        bot.run(DISCORD_TOKEN)
