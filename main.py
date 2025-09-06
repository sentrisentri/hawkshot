import nextcord
from nextcord.ext import commands
from nextcord import Interaction, SlashOption
import json
import aiohttp
import asyncio
import math
import utils
from dotenv import load_dotenv
import os
from pathlib import Path

load_dotenv()
activity = nextcord.Activity(type=nextcord.ActivityType.watching, name="your games")
client = commands.Bot(
    command_prefix="!", activity=activity, status=nextcord.Status.do_not_disturb
)



DATA_FILE = Path(__file__).with_name("riot_accounts.json")


def _normalize_accounts_for_serialization(accounts: list):
    """Ensure all game_mode containers are JSON-serializable lists."""
    for acc in accounts:
        if "channel" in acc:
            for ch in acc["channel"]:
                gm = ch.get("game_mode")
                if isinstance(gm, set):
                    ch["game_mode"] = sorted(list(gm))
    return accounts


def save_riot_accounts():
    """Persist riot_accounts to disk safely, creating the file if needed."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(_normalize_accounts_for_serialization(riot_accounts), f, indent=4)

# ---- Embed Builders ----
def create_lol_embed(account, match_data, participant_obj, gamemode_obj, map_obj, emojis):
    """Create a standardized LoL match embed"""
    lol_mode_id = match_data["info"]["queueId"]
    game_duration = match_data["info"]["gameDuration"]
    
    kills = participant_obj["kills"]
    deaths = participant_obj["deaths"]
    assists = participant_obj["assists"]
    damage = participant_obj["totalDamageDealtToChampions"]
    
    queue_id = gamemode_obj["description"].replace(" games", "").replace("5v5", "")
    minion_kills = int(participant_obj["totalMinionsKilled"]) + int(participant_obj["neutralMinionsKilled"])
    minutes = max(1, math.floor(int(game_duration) / 60))
    csm = str(round(minion_kills / minutes, 2))
    kda_ratio = round(((kills + assists) / (1 if deaths == 0 else deaths)), 2)

    # Title logic
    if lol_mode_id == 1700:  # Arena
        title = (
            f"{account['summoner_name']} has placed "
            f"{participant_obj.get('placement', '?')}"
            f"{'st!' if participant_obj.get('placement') == 1 else 'nd!' if participant_obj.get('placement') == 2 else 'rd!' if participant_obj.get('placement') == 3 else 'th!'}"
        )
    else:
        if participant_obj["win"]:
            title = f"{account['summoner_name']} has won their match!"
        elif game_duration <= 300 and participant_obj.get("gameEndedInEarlySurrender"):
            title = f"{account['summoner_name']} has remade their match!"
        else:
            title = f"{account['summoner_name']} has lost their match!"

    # Color logic
    if participant_obj["win"]:
        color = 0x32dc65  # Green
    elif game_duration <= 300 and participant_obj.get("gameEndedInEarlySurrender"):
        color = 0xE1E1E1  # Gray
    else:
        color = 0xFA4453  # Red

    embed = nextcord.Embed(title=title, color=color)
    
    thumbnail_url = f"https://cdn.communitydragon.org/latest/champion/{participant_obj['championId']}/square"
    embed.set_thumbnail(url=thumbnail_url)
    
    embed.set_footer(
        text=f"{minutes} Minutes {int(game_duration) % 60} Seconds - {utils.get_region(account['region'])} - League of Legends"
    )
    
    field_name = queue_id + ("" if lol_mode_id == 1700 else f" - {map_obj['name']}")
    field_value = (
        f"{kills}/{deaths}/{assists} - {kda_ratio} Ratio\n"
        f"{'%s CS - %s CS/M' % (minion_kills, csm) if lol_mode_id != 1700 else '%s Damage' % damage}"
    )
    
    embed.add_field(name=field_name, value=field_value, inline=False)
    embed.add_field(name="".join(str(e) for e in emojis), value="", inline=False)
    
    return embed

def create_tft_embed(account, match_data, participant_obj, gamemode_obj, companion_obj):
    """Create a standardized TFT match embed"""
    placement = int(participant_obj["placement"])
    
    # Title
    placement_suffix = "st" if placement == 1 else "nd" if placement == 2 else "rd" if placement == 3 else "th"
    title = f"{account['summoner_name']} has placed {placement}{placement_suffix} in their match!"
    
    # Color
    if placement == 1:
        color = 0x32dc65  # Gold
    elif placement <= 4:
        color = 0xFFA600  # Orange
    else:
        color = 0xFA4453  # Red
    
    embed = nextcord.Embed(title=title, color=color)
    
    # Thumbnail
    if companion_obj:
        icon = companion_obj["loadoutsIcon"].replace("/lol-game-data/assets/ASSETS/Loadouts/Companions/", "")
        thumbnail_url = f"https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/assets/loadouts/companions/{icon.lower()}"
        embed.set_thumbnail(url=thumbnail_url)
    
    # Footer
    tft_minutes = math.floor(int(participant_obj["time_eliminated"]) / 60)
    tft_seconds = int(participant_obj["time_eliminated"]) % 60
    embed.set_footer(
        text=f"{tft_minutes} Minutes {tft_seconds} Seconds - {utils.get_region(account['region'])} - Teamfight Tactics"
    )
    
    # Field
    stage1 = math.floor(((int(participant_obj["last_round"]) - 4) / 7) + 2)
    stage2 = (int(participant_obj["last_round"]) - 4) % 7
    field_name = f"{gamemode_obj['description']} - Set {match_data['info']['tft_set_number']}"
    field_value = f"Level {participant_obj['level']} - Survived to {stage1}-{stage2}"
    
    embed.add_field(name=field_name, value=field_value, inline=False)
    
    return embed

# ---- Static Data Cache ----
_static_cache = {
    "queues": None,
    "maps": None,
    "companions": None,
    "last_fetch": {}
}

async def get_queues_data():
    """Cached queue data fetcher"""
    if _static_cache["queues"] is None:
        url = "https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/v1/queues.json"
        data = await async_get(url)
        if data:
            _static_cache["queues"] = data
    return _static_cache["queues"]

async def get_maps_data():
    """Cached map data fetcher"""
    if _static_cache["maps"] is None:
        url = "https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/v1/maps.json"
        data = await async_get(url)
        if data:
            _static_cache["maps"] = data
    return _static_cache["maps"]

async def get_companions_data():
    """Cached companion data fetcher"""
    if _static_cache["companions"] is None:
        url = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/companions.json"
        data = await async_get(url)
        if data:
            _static_cache["companions"] = data
    return _static_cache["companions"]

async def find_queue_by_id(queue_id):
    """Find queue info by ID, handling both dict and list formats"""
    queues = await get_queues_data()
    if not queues:
        return {"description": f"Queue {queue_id}"}
    
    if isinstance(queues, dict):
        return queues.get(str(queue_id)) or queues.get(int(queue_id)) or {"description": f"Queue {queue_id}"}
    else:
        for q in queues:
            if isinstance(q, dict) and q.get("id") == queue_id:
                return q
        return {"description": f"Queue {queue_id}"}

async def find_map_by_id(map_id):
    """Find map info by ID"""
    maps = await get_maps_data()
    if not maps:
        return {"name": f"Map {map_id}"}
    
    for m in maps:
        if isinstance(m, dict) and m.get("id") == map_id:
            return m
    return {"name": f"Map {map_id}"}

async def find_companion_by_id(content_id):
    """Find companion info by content ID"""
    companions = await get_companions_data()
    if not companions:
        return None
    
    for companion in companions:
        if isinstance(companion, dict) and companion.get("contentId") == content_id:
            return companion
    return None

# ---- HTTP Client Helper ----
_http_session = None

async def get_http_session():
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()
    return _http_session

async def async_get(url, headers=None, timeout=10):
    """Async HTTP GET wrapper"""
    try:
        session = await get_http_session()
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
            if response.content_type == 'application/json':
                return await response.json()
            return await response.text()
    except Exception as e:
        print(f"[hawkshot] HTTP GET failed for {url}: {e}")
        return None

# ---- Interaction helpers ----
async def maybe_defer(interaction: nextcord.Interaction):
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
    except Exception as e:
        print(f"[hawkshot] defer failed: {e}")

async def send_reply(interaction: nextcord.Interaction, content=None, *, embed=None, ephemeral=False):
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content, embed=embed, ephemeral=ephemeral)
    except Exception as e:
        print(f"[hawkshot] reply failed: {e}")


@client.event
async def on_ready():
    global riot_accounts
    if not DATA_FILE.exists():
        # Create an empty store if missing
        DATA_FILE.write_text("[]", encoding="utf-8")
    try:
        with DATA_FILE.open("r", encoding="utf-8") as json_read:
            riot_accounts = json.load(json_read)
            if not isinstance(riot_accounts, list):  # Fallback if corrupted
                riot_accounts = []
    except (json.JSONDecodeError, OSError):
        riot_accounts = []
        save_riot_accounts()
    print(f"Bot is ready | loaded {len(riot_accounts)} accounts from disk")
    # Repair pass: ensure tft_puuid valid (400 decrypt issues happen if we mis-stored something)
    repaired = False
    for acc in riot_accounts:
        # If tft_puuid missing or same but TFT endpoint rejects, we will refresh lazily later
        if not acc.get("tft_puuid"):
            # Try fetch from TFT summoner by name (strip tag if Riot ID)
            base_name = acc.get("summoner_name", "").split("#",1)[0]
            tft_id_url = f"https://{acc['region']}.api.riotgames.com/tft/summoner/v1/summoners/by-name/{base_name}"
            try:
                session = await get_http_session()
                async with session.get(tft_id_url, headers=utils.tft_headers) as r:
                    if r.status == 200:
                        data = await r.json()
                        acc["tft_puuid"] = data.get("puuid")
                        repaired = True
            except Exception as e:
                print(f"[hawkshot] Failed to repair tft_puuid for {base_name}: {e}")
    if repaired:
        print("[hawkshot] Repaired missing tft_puuid values on startup")
        save_riot_accounts()
    # start background polling task
    client.loop.create_task(check_account())
    # start cache cleanup task
    client.loop.create_task(periodic_cache_cleanup())

async def cleanup():
    """Cleanup resources on shutdown"""
    global _http_session, _static_cache
    if _http_session and not _http_session.closed:
        await _http_session.close()
    # Clear caches
    _static_cache.clear()

async def periodic_cache_cleanup():
    """Periodically clean up old cache entries"""
    import time
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            current_time = time.time()
            # Clean up utils rate cache entries older than 1 hour
            for cache_type in utils._rate_cache:
                for puuid in list(utils._rate_cache[cache_type].keys()):
                    entry = utils._rate_cache[cache_type][puuid]
                    if current_time - entry.get("ts", 0) > 3600:
                        del utils._rate_cache[cache_type][puuid]
            # Clean up backoff entries that have expired
            for cache_type in utils._backoff:
                for puuid in list(utils._backoff[cache_type].keys()):
                    if current_time > utils._backoff[cache_type][puuid]:
                        del utils._backoff[cache_type][puuid]
            print("[hawkshot] Cache cleanup completed")
        except Exception as e:
            print(f"[hawkshot] Cache cleanup error: {e}")

@client.event
async def on_disconnect():
    await cleanup()

def ensure_accounts_loaded():
    global riot_accounts
    if riot_accounts:
        return
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    riot_accounts = data
                    print(f"[hawkshot] Lazy-loaded {len(riot_accounts)} accounts")
        except Exception as e:
            print(f"[hawkshot] Lazy load failed: {e}")


riot_accounts = []  # List to store Riot accounts

async def resolve_account_lookup(input_name: str, region: str):
    """Return (account_dict|None, canonical_display_name, puuid|None) for a user input.
    Supports Riot ID (gameName#tagLine) and legacy stored names.
    """
    # Riot ID path
    if "#" in input_name:
        acct = await utils.get_account_by_riot_id(input_name, region)
        if acct:
            puuid = acct.get("puuid")
            # Try match existing by puuid
            for stored in riot_accounts:
                if stored.get("puuid") == puuid and stored.get("region") == region:
                    return stored, stored.get("summoner_name", input_name), puuid
            # Not stored yet
            display = f"{acct.get('gameName')}#{acct.get('tagLine')}"
            return None, display, puuid
        return None, input_name, None
    # Legacy path
    for stored in riot_accounts:
        if stored.get("region") == region and stored.get("summoner_name", "").lower() == input_name.lower():
            return stored, stored.get("summoner_name"), stored.get("puuid")
    return None, input_name, None



@client.slash_command()
async def watch(
    interaction: nextcord.Interaction,
    summoner_name: str,
    region: str = SlashOption(
        name="region",
        description="Please pick a region",
        choices={
            "EUW": "euw1",
            "NA": "na1",
            "EUNE": "eun1",
            "KR": "kr",
            "JP": "jp1",
            "OCE": "oc1",
            "BR": "br1",
            "LAN": "la1",
            "LAS": "la2",
            "RU": "ru",
            "TR": "tr1",
        },
    ),
    game_mode: str = SlashOption(
        name="gamemode",
        description="Please pick a game mode",
        choices={
            "Quickplay": "490",
            "Ranked Solo/Duo": "420",
            "Ranked Flex": "440",
            "ARAM": "450",
            "Arena": "1700",
            "Nexus Blitz": "1300",
            "All": "all",
            
        },
    ),
    channel: nextcord.TextChannel = SlashOption(
        name="channel",
        description="Please pick a channel",
    ),
):
    ensure_accounts_loaded()
    guild_id = interaction.guild.id
    await maybe_defer(interaction)

    user = None  # declaring the variable

    # Normalize Riot ID vs legacy name
    resolved_display_name = summoner_name
    riot_account_data = None
    if "#" in summoner_name:
        riot_account_data = await utils.get_account_by_riot_id(summoner_name, region)
        if riot_account_data:
            # Use PUUID and canonical gameName#tagLine capitalization
            resolved_display_name = f"{riot_account_data['gameName']}#{riot_account_data['tagLine']}"
    
    for account in riot_accounts:  # iterating the array
        # Compare by stored summoner_name (which may now be Riot ID) and region
        if account["summoner_name"].lower() == resolved_display_name.lower() and account["region"] == region:
            user = account

    if user:  # if user is not equal to None
        # create a variable called channels and equal it to the users channels
        channels = user["channel"]

        for chan in channels:  # iterate the channels array
            if chan["Channel ID"] == channel.id and chan["Guild ID"] == guild_id:  # if the channel inputted is already in the array      
                # output for user
                if game_mode in chan["game_mode"] or "all" in chan["game_mode"]: 
                    await send_reply(interaction, "This Riot account is already in this channel.") 
                    return           
                else:
                    chan["game_mode"].append(game_mode) 
                    await send_reply(interaction, f"Added {utils.get_game_mode(game_mode)} games to this player in this channel.") 
                
                    return  # stop bot
            
    # fetch the method from the api
    if riot_account_data:
        puuid = riot_account_data["puuid"]
        # Need LoL summoner object for level/icon etc later
        summoner_obj = await utils.get_summoner_by_puuid(puuid, region)
        if summoner_obj is None:
            await send_reply(interaction, "Could not resolve summoner from Riot ID")
            return
    else:
        url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{summoner_name}"
        try:
            session = await get_http_session()
            async with session.get(url, headers=utils.headers) as response:
                if response.status != 200:
                    if response.status == 404:
                        await send_reply(interaction, "Summoner not found")
                    elif response.status == 403:
                        await send_reply(interaction, "403 Forbidden: Riot API rejected the request (expired dev key / wrong key / routing).")
                    else:
                        await send_reply(interaction, f"{response.status}: Riot API error. Check logs and key.")
                    return
                summoner_obj = await response.json()
                puuid = summoner_obj["puuid"]
        except Exception as e:
            await send_reply(interaction, f"Error fetching summoner data: {e}")
            return
    # fetch recent matches using puuid
    # get the match ids and store it in match_response
    match_response = await utils.get_match_ids(puuid, region)

    # Distinct TFT PUUID using TFT_API_KEY
    tft_summoner_puuid = await utils.get_tft_puuid(resolved_display_name, region)
    tft_match_ids = await utils.get_tft_match_ids(tft_summoner_puuid, region) if tft_summoner_puuid else None

    
    if user:  # existing watched user
        user["channel"].append({"Channel ID": channel.id, "Guild ID": guild_id, "game_mode": {game_mode}})
        for index, account in enumerate(riot_accounts):
            if user["summoner_name"].lower() == resolved_display_name.lower() and user["region"] == region:
                riot_accounts[index] = user
                break
        save_riot_accounts()
        await send_reply(interaction, f"Successfully watching {resolved_display_name}'s ({region}) {utils.get_game_mode(game_mode)} games in this channel!")
        return
    # New user path
    display_name_for_store = resolved_display_name if riot_account_data else await utils.get_summoner_name(summoner_name, region)
    riot_account = {
        "region": region,
        "summoner_name": display_name_for_store,
        "last_match": None if match_response is None else match_response[0],
        "tft_last_match": None if tft_match_ids is None else tft_match_ids[0],
        "puuid": puuid,
        "tft_puuid": tft_summoner_puuid,
        "channel": [
            {"Channel ID": channel.id, "Guild ID": guild_id, "game_mode": {game_mode}},
        ],
    }
    riot_accounts.append(riot_account)
    save_riot_accounts()
    await send_reply(interaction, f"Successfully watching {display_name_for_store}'s ({region}) {utils.get_game_mode(game_mode)} games in this channel!")


@client.slash_command()
async def unwatch(
    interaction: nextcord.Interaction,
    summoner_name: str,
    region: str = SlashOption(
        name="region",
        description="Please pick a region",
        choices={
            "EUW": "euw1",
            "NA": "na1",
            "EUNE": "eun1",
            "KR": "kr",
            "JP": "jp1",
            "OCE": "oc1",
            "BR": "br1",
            "LAN": "la1",
            "LAS": "la2",
            "RU": "ru",
            "TR": "tr1",
        },
    ),
    channel: nextcord.TextChannel = SlashOption(
        name="channel",
        description="Please pick a channel",
    ),
):
    ensure_accounts_loaded()
    await maybe_defer(interaction)
    guild_id = interaction.guild.id

    user, resolved_name, _ = await resolve_account_lookup(summoner_name, region)

    if user:
        # Find and remove the channel from this user's watch list
        channel_removed = False
        for chanel in user["channel"][:]:  # Create a copy to avoid modification during iteration
            if chanel["Channel ID"] == channel.id and chanel["Guild ID"] == guild_id:
                user["channel"].remove(chanel)
                channel_removed = True
                break

        if channel_removed:
            # Update the account in the global list
            for index, account in enumerate(riot_accounts):
                if (account["summoner_name"] == user["summoner_name"] and 
                    account["region"] == user["region"] and
                    account.get("puuid") == user.get("puuid")):
                    riot_accounts[index] = user
                    break

            save_riot_accounts()
            await send_reply(interaction, f"Stopped watching {resolved_name} in this channel")
        else:
            await send_reply(interaction, f"{resolved_name} is not being watched in this channel")
    else:
        await send_reply(interaction, f"{resolved_name} is not currently being watched")


                    
async def check_account():
    while True:
        try:
            if len(riot_accounts) == 0:
                print("No Riot accounts to check")
                await asyncio.sleep(30)
                continue

            for account in riot_accounts:
                try:
                    match_ids = await utils.get_match_ids(account["puuid"], account["region"])
                    if match_ids is None:
                        continue

                    if match_ids[0] != account["last_match"]:
                        print(f"New LoL match found for {account['summoner_name']}")
                        account["last_match"] = match_ids[0]
                        match_data = await utils.get_match_data(
                            account["last_match"], account["region"]
                        )
                        
                        if match_data is None:
                            print(f"[hawkshot] Failed to fetch match data for {account['summoner_name']}")
                            continue

                        lol_mode_id = match_data["info"]["queueId"]
                        gamemodeObj = await find_queue_by_id(lol_mode_id)

                        participantObj = None
                        for participant in match_data["info"]["participants"]:
                            if (participant["puuid"]) == account["puuid"]:
                                participantObj = participant
                                break
                            
                        
                        
                        # Collect emoji data
                        emojis = []
                        for i in range(7):
                            emoji = nextcord.utils.get(client.emojis, name=str(participantObj[f"item{i}"]))
                            emojis.append(emoji if emoji else "")
                        
                        # Get map data
                        mapid = match_data["info"]["mapId"]
                        mapObj = await find_map_by_id(mapid)
                        
                        # Create embed using builder
                        lol_embed = create_lol_embed(account, match_data, participantObj, gamemodeObj, mapObj, emojis)
                        
                  
                        for channel in account["channel"]:
                            if "all" in channel["game_mode"] or str(lol_mode_id) in channel["game_mode"]:
                                guild = client.get_guild(channel["Guild ID"])
                                channel_obj = guild.get_channel(channel["Channel ID"])
                                await channel_obj.send(embed=lol_embed)
                            else:
                                continue
                except Exception as e:
                    print(f"[hawkshot] Error processing LoL match for {account.get('summoner_name', 'unknown')}: {e}")

            for account in riot_accounts:
                try:
                    if not account.get("tft_puuid"):
                        continue
                        
                    tft_match_ids = await utils.get_tft_match_ids(
                        account["tft_puuid"], account["region"]
                    )

                    if tft_match_ids is None:
                        continue
                    
                    if tft_match_ids[0] != account["tft_last_match"]:
                        print(f"New TFT match found for {account['summoner_name']}")
                        account["tft_last_match"] = tft_match_ids[0]
                        tft_match_data = await utils.get_tft_match_data(
                        account["tft_last_match"], account["region"]
                        )

                        participantObj = None
                        for participant in tft_match_data["info"]["participants"]:
                            if (participant["puuid"]) == account["tft_puuid"]:
                                participantObj = participant
                                break

                        matchid = tft_match_data["info"]["queue_id"]
                        tftgamemodeObj = await find_queue_by_id(matchid)

                        companionObj = await find_companion_by_id(participantObj["companion"]["content_ID"])
                        
                        # Create embed using builder
                        tft_embed = create_tft_embed(account, tft_match_data, participantObj, tftgamemodeObj, companionObj)

                        for channel in account["channel"]:
                            guild = client.get_guild(channel["Guild ID"])
                            channel_obj = guild.get_channel(channel["Channel ID"])
                            await channel_obj.send(embed=tft_embed)
                except Exception as e:
                    print(f"[hawkshot] Error processing TFT match for {account.get('summoner_name', 'unknown')}: {e}")

            save_riot_accounts()
            print("Updated the Riot accounts")
        except Exception as e:
            print(f"[hawkshot] Critical error in check_account loop: {e}")
        
        await asyncio.sleep(30)  # reduced polling frequency to ease rate limits

#async def check_tftrankup():
    # while True:
    #     if len(riot_accounts) == 0:
    #         print("no ranks to check")
    #         await asyncio.sleep(20)
    #         continue
    #     for account in riot_accounts:
    #         if account["tft_rank"] != await utils.get_tft_summoner_rank(account["summoner_name"], account["region"]):
                

@client.slash_command()
async def profile(
    interaction: nextcord.Interaction,
    summoner_name: str,
    region: str = SlashOption(
        name="region",
        description="Please pick a region",
        choices={
            "EUW": "euw1",
            "NA": "na1",
            "EUNE": "eun1",
            "KR": "kr",
            "JP": "jp1",
            "OCE": "oc1",
            "BR": "br1",
            "LAN": "la1",
            "LAS": "la2",
            "RU": "ru",
            "TR": "tr1",
        },
    ),
     
    
):
    ensure_accounts_loaded()
    await maybe_defer(interaction)
    
    user, resolved_name, _ = await resolve_account_lookup(summoner_name, region)
    if user is None:
        await send_reply(interaction, f"{resolved_name} is not currently being watched")
        return

    print(f"[hawkshot] Profile lookup for {resolved_name}, PUUID: {user.get('puuid', 'None')[:8]}...")

    # Use PUUID to get summoner data (works for both legacy names and Riot IDs)
    summoner_data = await utils.get_summoner_by_puuid(user["puuid"], user["region"])
    if summoner_data is None:
        # Fallback: try by name if it's not a Riot ID format
        if "#" not in user["summoner_name"]:
            print(f"[hawkshot] PUUID lookup failed, trying by name: {user['summoner_name']}")
            summoner_data = await utils.get_summoner_by_name_direct(user["summoner_name"], user["region"])
        
        if summoner_data is None:
            await send_reply(interaction, f"Could not fetch summoner data for {resolved_name}")
            return
    
    # Get summoner ID separately since it might not be in the summoner data
    summoner_id = summoner_data.get("id")
    if not summoner_id:
        summoner_id = await utils.get_summoner_id_by_puuid(user["puuid"], user["region"])
        if not summoner_id:
            print(f"[hawkshot] Could not get summoner ID for {resolved_name}, using PUUID-based functions")
            
    thumbnail_url = f"https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/profile-icons/{summoner_data.get('profileIconId', 0)}.jpg"
        
    # Get champion mastery and ranks - use PUUID-based functions if no summoner ID
    if summoner_id and summoner_id != user["puuid"]:
        try:
            highest_champ = await utils.get_highest_champion_mastery_by_id(summoner_id, user["region"])
            solo_rank = await utils.get_solo_summoner_rank_by_id(summoner_id, user["region"])
            flex_rank = await utils.get_flex_summoner_rank_by_id(summoner_id, user["region"])
        except Exception as e:
            print(f"[hawkshot] Error getting data via summoner ID: {e}")
            highest_champ = "Unknown"
            solo_rank = "Unranked"
            flex_rank = "Unranked"
    else:
        try:
            highest_champ = await utils.get_highest_champion_mastery_by_puuid(user["puuid"], user["region"])
            solo_rank = await utils.get_solo_summoner_rank_by_puuid(user["puuid"], user["region"])
            flex_rank = await utils.get_flex_summoner_rank_by_puuid(user["puuid"], user["region"])
        except Exception as e:
            print(f"[hawkshot] Error getting data via PUUID: {e}")
            highest_champ = "Unknown"
            solo_rank = "Unranked"
            flex_rank = "Unranked"
    
    try:
        # Use TFT PUUID if available, otherwise fall back to name-based lookup
        if "tft_puuid" in user and user["tft_puuid"]:
            tft_rank = await utils.get_tft_summoner_rank_by_puuid(user["tft_puuid"], user["region"])
        else:
            tft_rank = await utils.get_tft_summoner_rank(user["summoner_name"], user["region"])
    except Exception as e:
        print(f"[hawkshot] Error getting TFT rank: {e}")
        tft_rank = "Unranked"
        
    profile_embed = nextcord.Embed( 
        title = f"{resolved_name}'s Profile",
        description = f"Level {summoner_data['summonerLevel']}\nMost Played Champ: {highest_champ}",
        color=0x60A5FA
    )
    
    profile_embed.add_field(
        name = "LOL Rank",
        value= f"Solo/Duo Rank: {solo_rank}\nFlex Rank: {flex_rank}")
    
    profile_embed.add_field(
        name ="TFT Rank",
        value=tft_rank, inline=False)
    profile_embed.set_thumbnail(url=thumbnail_url)   
    
    await send_reply(interaction, embed=profile_embed)
            

    
    
@client.slash_command()
async def last_game(
    interaction: nextcord.Interaction,
    summoner_name: str,
     region: str = SlashOption(
        name="region",
        description="Please pick a region",
        choices={
            "EUW": "euw1",
            "NA": "na1",
            "EUNE": "eun1",
            "KR": "kr",
            "JP": "jp1",
            "OCE": "oc1",
            "BR": "br1",
            "LAN": "la1",
            "LAS": "la2",
            "RU": "ru",
            "TR": "tr1",
        },
    ),
    game: str = SlashOption(
        name="game",
        description="Please pick a game",
        choices = {
            "League of Legends": "lol",
            "Teamfight Tactics": "tft"
        },
    ),
            
    


):
    ensure_accounts_loaded()
    user, resolved_name, _ = await resolve_account_lookup(summoner_name, region)
    if user is None:
        await send_reply(interaction, f"{resolved_name} is not currently being watched")
        return

    if user:
        if game == "lol":
            match_data = await utils.get_match_data(user["last_match"], user["region"])
            if match_data is None and not user.get("last_match"):
                # Try to initialize last_match on demand
                match_ids = await utils.get_match_ids(user["puuid"], user["region"])
                if match_ids:
                    user["last_match"] = match_ids[0]
                    match_data = await utils.get_match_data(user["last_match"], user["region"])
                    save_riot_accounts()
            if match_data is None:
                await send_reply(interaction, "No recent League match found")
                return
            lol_mode_id = match_data["info"]["queueId"]
            gamemodeObj = await find_queue_by_id(lol_mode_id)

            participantObj = None
            for participant in match_data["info"]["participants"]:
                if (participant["puuid"]) == user["puuid"]:
                    participantObj = participant
                    break

            mapid = match_data["info"]["mapId"]
            mapObj = await find_map_by_id(mapid)

            # Build embed using helper
            emojis = []
            for i in range(7):
                emoji = nextcord.utils.get(client.emojis, name=str(participantObj[f"item{i}"]))
                emojis.append(emoji if emoji else "")

            lol_embed = create_lol_embed(user, match_data, participantObj, gamemodeObj, mapObj, emojis)
            await send_reply(interaction, embed=lol_embed)
        elif game == "tft":
            if utils.is_tft_disabled():
                await send_reply(interaction, "TFT disabled (invalid or missing TFT_API_KEY / prior 403). Refresh key and restart.")
                return
            # Initialize tft_last_match lazily if missing
            if not user.get("tft_last_match"):
                tft_ids = await utils.get_tft_match_ids(user["tft_puuid"], user["region"])
                if tft_ids:
                    user["tft_last_match"] = tft_ids[0]
                    save_riot_accounts()
            tft_match_data = await utils.get_tft_match_data(user.get("tft_last_match"), user["region"])
            if tft_match_data is None:
                # Attempt a one-time tft_puuid refresh then retry
                base_name = user["summoner_name"].split("#",1)[0]
                refresh_url = f"https://{user['region']}.api.riotgames.com/tft/summoner/v1/summoners/by-name/{base_name}"
                try:
                    session = await get_http_session()
                    async with session.get(refresh_url, headers=utils.tft_headers) as r:
                        if r.status == 200:
                            data = await r.json()
                            new_puuid = data.get("puuid")
                            if new_puuid and new_puuid != user.get("tft_puuid"):
                                user["tft_puuid"] = new_puuid
                                ids_retry = await utils.get_tft_match_ids(new_puuid, user["region"])
                                if ids_retry:
                                    user["tft_last_match"] = ids_retry[0]
                                    save_riot_accounts()
                                    tft_match_data = await utils.get_tft_match_data(user["tft_last_match"], user["region"])
                except Exception as e:
                    print(f"[hawkshot] TFT PUUID refresh failed: {e}")
                if tft_match_data is None:
                    await send_reply(interaction, "No TFT match data available (possibly no recent games).")
                    return
            participantObj = None
            for participant in tft_match_data["info"]["participants"]:
                if (participant["puuid"]) == user["tft_puuid"]:
                    participantObj = participant
                    break
            matchid = tft_match_data["info"]["queue_id"]
            tftgamemodeObj = await find_queue_by_id(matchid)
            companionObj = await find_companion_by_id(participantObj["companion"]["content_ID"])
            tft_embed = create_tft_embed(user, tft_match_data, participantObj, tftgamemodeObj, companionObj)
            await send_reply(interaction, embed=tft_embed)

@client.slash_command()
async def status(interaction: nextcord.Interaction):
    """Show bot status and cleanup orphaned channels"""
    ensure_accounts_loaded()
    
    await maybe_defer(interaction)
    
    # Count statistics
    total_accounts = len(riot_accounts)
    total_channels = sum(len(acc.get("channel", [])) for acc in riot_accounts)
    
    # Clean up orphaned channels (channels that no longer exist)
    cleaned = 0
    for account in riot_accounts:
        valid_channels = []
        for channel_info in account.get("channel", []):
            try:
                guild = client.get_guild(channel_info["Guild ID"])
                if guild:
                    channel_obj = guild.get_channel(channel_info["Channel ID"])
                    if channel_obj:
                        valid_channels.append(channel_info)
                    else:
                        cleaned += 1
                        print(f"[hawkshot] Cleaned orphaned channel {channel_info['Channel ID']} from {account['summoner_name']}")
                else:
                    cleaned += 1
                    print(f"[hawkshot] Cleaned orphaned guild {channel_info['Guild ID']} from {account['summoner_name']}")
            except Exception as e:
                print(f"[hawkshot] Error checking channel {channel_info}: {e}")
                cleaned += 1
        account["channel"] = valid_channels
    
    # Remove accounts with no channels
    empty_accounts = [acc for acc in riot_accounts if not acc.get("channel")]
    for acc in empty_accounts:
        riot_accounts.remove(acc)
        print(f"[hawkshot] Removed account {acc['summoner_name']} (no channels)")
    
    if cleaned > 0 or empty_accounts:
        save_riot_accounts()
    
    # API status
    tft_status = "Disabled" if utils.is_tft_disabled() else "Enabled"
    cache_entries = sum(len(cache) for cache in utils._rate_cache.values())
    
    embed = nextcord.Embed(title="Hawkshot Status", color=0x60A5FA)
    embed.add_field(name="Watched Accounts", value=str(total_accounts), inline=True)
    embed.add_field(name="Total Channels", value=str(total_channels), inline=True)
    embed.add_field(name="TFT Status", value=tft_status, inline=True)
    embed.add_field(name="Cache Entries", value=str(cache_entries), inline=True)
    embed.add_field(name="Cleaned Channels", value=str(cleaned), inline=True)
    embed.add_field(name="Removed Accounts", value=str(len(empty_accounts)), inline=True)
    
    await send_reply(interaction, embed=embed)

@client.slash_command()
async def current_game(
    interaction: nextcord.Interaction,
    summoner_name: str,
    region: str = SlashOption(
        name="region",
        description="Please pick a region",
        choices={
            "EUW": "euw1",
            "NA": "na1",
            "EUNE": "eun1",
            "KR": "kr",
            "JP": "jp1",
            "OCE": "oc1",
            "BR": "br1",
            "LAN": "la1",
            "LAS": "la2",
            "RU": "ru",
            "TR": "tr1",
        },
    ),
    


):
    user = None
    for account in riot_accounts:
        if account["summoner_name"] == summoner_name and account["region"] == region:
            user = account
            break
    if user is None:
        await send_reply(interaction, "This user is not linked/does not exist")
        return
    
    if user:
        print(await utils.get_summoner_id(user["summoner_name"], user["region"]))
        esid = user["puuid"]
        print(esid)

discord_token = os.getenv("TOKEN")
if not discord_token or not isinstance(discord_token, str):
    print("[hawkshot] ERROR: Discord bot token not found. Set TOKEN in your .env file, e.g.\nTOKEN=your_bot_token_here")
    print("[hawkshot] The process will exit without starting the bot.")
else:
    # Note: API key check disabled in sync context - will check during first API call
    print("[hawkshot] Bot starting...")
    client.run(discord_token)
