import nextcord
from nextcord.ext import commands
from nextcord import Interaction, SlashOption
import json
import requests
import asyncio
import math
import utils
import dotenv
from dotenv import load_dotenv
import os

load_dotenv()
activity = nextcord.Activity(type=nextcord.ActivityType.watching, name="Fixing the bot (doesnt make sense idc)")
client = commands.Bot(
    command_prefix="!", activity=activity, status=nextcord.Status.do_not_disturb
)
ddragonver = "13.14.1"


@client.event
async def on_ready():
    global riot_accounts
    json_read = open("riot_accounts.json", "r")
    riot_accounts = json.load(json_read)
    json_read.close()
    print("Bot is ready")
    await check_account()


riot_accounts = []  # List to store Riot accounts

pp = "pp"


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
    channel: nextcord.TextChannel = SlashOption(
        name="channel",
        description="Please pick a channel",
    ),
):
    guild_id = interaction.guild.id

    user = None  # declaring the variable

    for account in riot_accounts:  # iterating the array
        # if the summoner name and region is equal (but not the channel) to any of the ones in the json file
        if account["summoner_name"] == summoner_name and account["region"] == region:
            user = account  # set the user variable to account

    if user:  # if user is not equal to None
        # create a variable called channels and equal it to the users channels
        channels = user["channel"]

        for chan in channels:  # iterate the channels array
            if chan == channel.id:  # if the channel inputted is already in the array
                # output for user
                await interaction.response.send_message(
                    "This Riot account is already in this channel."
                )
                return  # stop bot
            
    # fetch the method from the api
    url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{summoner_name}"
    # fetch the response and store it
    response = requests.get(url, headers=utils.headers)

    if response.status_code != 200:  # if the respone is bad
        # output for user
        if response.status_code == 404:
            await interaction.response.send_message("Summoner not found")
        else:
            await interaction.response.send_message(response.status_code + ": API Key is probably expired, pls wait")
        return  # stop the bot

    puuid = response.json()["puuid"]  # fetch the puuid and store it
    # get the match ids and store it in match_response
    match_response = await utils.get_match_ids(puuid, region)
    tft_match_response = await utils.get_tft_match_ids(puuid, region)

    if summoner_name == "rivalzfb":
        await interaction.response.send_message("You cannot watch this user")
        return
    
    
    if user:  # if user is not None
        # add the channelid to the channel array
        user["channel"].append({"Channel ID": channel.id, "Guild ID": guild_id})

        # index the riot_accounts array and iterate through it to see it the summoner name and region is = to the one provided
        for index, account in enumerate(riot_accounts):
            if user["summoner_name"] == summoner_name and user["region"] == region:
                # set the channelids in the array to the one provided
                riot_accounts[index] = user

        with open("riot_accounts.json", "w") as f:
            json.dump(riot_accounts, f, indent=4, default=list)  # save it in the json
            

        # output for user
        await interaction.response.send_message(
            f"Successfully watching Riot account {summoner_name} ({region}) in this channel!"
        )
    else:  # if the user is not valid
        riot_account = {  # create a new object to store the riot account
            "region": region,
            "summoner_name": summoner_name,
            "last_match": None if len(match_response) == 0  else match_response[0],
            "tft_last_match": None if len(tft_match_response) == 0 else tft_match_response[0],
            "puuid": puuid,
            "channel": [
                {"Channel ID": channel.id, "Guild ID": guild_id},
            ],
        }

        riot_accounts.append(riot_account)  # add it to the array

        with open("riot_accounts.json", "w") as f:  # save it to the json
            json.dump(riot_accounts, f, indent=4, default=list)

        # output for the user
        await interaction.response.send_message(
            f"Successfully watching Riot account {summoner_name} ({region}) in this channel!"
        )


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
    guild_id = interaction.guild.id

    user = None
    for account in riot_accounts:
        if account["summoner_name"] == summoner_name and account["region"] == region:
            user = account

    if user:
        for chanel in user["channel"]:
            if chanel["Channel ID"] == channel.id and chanel["Guild ID"] == guild_id:
                user["channel"].remove(chanel)
                await interaction.response.send_message(
                    "This user has removed from this channel"
                )
    else:
        await interaction.response.send_message(
            "This user is not being watched in this channel"
        )


async def check_account():
    global embed
    while True:
        if len(riot_accounts) == 0:
            print("No Riot accounts to check")
            await asyncio.sleep(20)
            continue

        for account in riot_accounts:
            match_ids = await utils.get_match_ids(account["puuid"], account["region"])
            if match_ids is None:
                continue

            if match_ids[0] != account["last_match"]:
                print("New match found")
                account["last_match"] = match_ids[0]
                match_data = await utils.get_match_data(
                    account["last_match"], account["region"]
                )

                lol_mode_id = match_data["info"]["queueId"]
                lol_url = "https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/v1/queues.json"
                gamemode_response = requests.get(lol_url)
                gamemode_response.json()

                gamemodeObj = None
                gamemodeObj = gamemode_response.json()[str(lol_mode_id)]

                participantObj = None
                for participant in match_data["info"]["participants"]:
                    if (participant["puuid"]) == account["puuid"]:
                        participantObj = participant
                        break

                mapid = match_data["info"]["mapId"]
                mapurl = "https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/v1/maps.json"
                mapObj = None
                map_response = requests.get(mapurl)
                map_response.json()

                for maps in map_response.json():
                    if maps["id"] == mapid:
                        mapObj = maps
                        break

                thumbnail_url = (
                    "https://ddragon.leagueoflegends.com/cdn/"
                    + ddragonver
                    + "/img/champion/"
                    + participantObj["championName"]
                    + ".png"
                )
                kills = participantObj["kills"]
                deaths = participantObj["deaths"]
                assists = participantObj["assists"]
                damage = participantObj["totalDamageDealtToChampions"]
                queueId = (
                    gamemodeObj["description"].replace(
                        " games",
                        "",
                    )
                ).replace("5v5", "")

                gameDuration = match_data["info"]["gameDuration"]
                minionKills = int(participantObj["totalMinionsKilled"]) + int(
                    participantObj["neutralMinionsKilled"]
                )

                minutes = math.floor(int(gameDuration) / 60)
                csm = str(round(minionKills / (minutes), 2))
                kdaratio = round(
                    ((kills + assists) / (1 if deaths == 0 else deaths)), 2
                )

                embed = nextcord.Embed(
                    title=(
                        (account["summoner_name"])
                        + " has placed "
                        + str(participantObj["placement"])
                        + (
                            "st!"
                            if participantObj["placement"] == 1
                            else "nd!"
                            if participantObj["placement"] == 2
                            else "rd!"
                            if participantObj["placement"] == 3
                            else "th!"
                        )
                    )
                    if lol_mode_id == 1700
                    else (
                        account["summoner_name"] + " has won their match!"
                        if participantObj["win"]
                        else (account["summoner_name"] + " has remade their match!")
                        if gameDuration <= 300
                        and participant["gameEndedInEarlySurrender"] == True
                        else (account["summoner_name"] + " has lost their match!")
                    ),
                    color=0x00FF00
                    if participantObj["win"]
                    else 0xE1E1E1
                    if gameDuration <= 300
                    and participant["gameEndedInEarlySurrender"] == True
                    else 0xFF0000,
                )
                embed.set_thumbnail(url=thumbnail_url)
                embed.set_footer(
                    text=str(minutes)
                    + " Minutes "
                    + str(int(gameDuration) % 60)
                    + " Seconds"
                    + " - "
                    + utils.get_region(account["region"])
                    + " - "
                    + "League of Legends"
                )
                embed.add_field(
                    name=(
                        (queueId)
                        + ("" if lol_mode_id == 1700 else " - " + mapObj["name"])
                    ),
                    value=str(kills)
                    + "/"
                    + str(deaths)
                    + "/"
                    + str(assists)
                    + " - "
                    + str(kdaratio)
                    + " Ratio\n"
                    + (("") if lol_mode_id == 1700 else str(minionKills))
                    + (("") if lol_mode_id == 1700 else " CS - ")
                    + (str(damage if lol_mode_id == 1700 else csm))
                    + (" Damage" if lol_mode_id == 1700 else " CS/M"),
                    inline=False,
                )

                for channel in account["channel"]:
                    guild = client.get_guild(channel["Guild ID"])
                    channel = guild.get_channel(channel["Channel ID"])

                    await channel.send(embed=embed)

        for account in riot_accounts:
            tft_match_ids = await utils.get_tft_match_ids(
                account["puuid"], account["region"]
            )

            if tft_match_ids is None or len(tft_match_ids) == 0:
                continue
            
            if tft_match_ids[0] != account["tft_last_match"]:
                print("New match found")
                account["tft_last_match"] = tft_match_ids[0]
                tft_match_data = await utils.get_tft_match_data(
                account["tft_last_match"], account["region"]
                )

                participantObj = None
                for participant in tft_match_data["info"]["participants"]:
                    if (participant["puuid"]) == account["puuid"]:
                        participantObj = participant
                        break

                matchid = tft_match_data["info"]["queue_id"]
                tft_url = "https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/v1/queues.json"
                tft_gamemode_response = requests.get(tft_url)
                tft_gamemode_response.json()

                tftgamemodeObj = None
                tftgamemodeObj = tft_gamemode_response.json()[str(matchid)]

                companion_url = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/companions.json"
                r = requests.get(companion_url)

                tfticon_url = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/assets/loadouts/companions/"
                tft_queueId = tftgamemodeObj["description"]
                tft_minutes = math.floor(int(participantObj["time_eliminated"]) / 60)
                tft_seconds = int(participantObj["time_eliminated"]) % 60

                placement = int(participantObj["placement"])
                stage1 = math.floor(((int(participantObj["last_round"]) - 4) / 7) + 2)
                stage2 = (int(participantObj["last_round"]) - 4) % 7
                tacticianid = participantObj["companion"]["content_ID"]

                companionObj = None
                for companion in r.json():
                    if companion["contentId"] == tacticianid:
                        companionObj = companion

                icon = companionObj["loadoutsIcon"].replace(
                    "/lol-game-data/assets/ASSETS/Loadouts/Companions/", ""
                )
                thumbnail_url = (
                    "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/assets/loadouts/companions/"
                ) + (icon.lower())
                tft_embed = nextcord.Embed(
                    title=(account["summoner_name"])
                    + " has placed "
                    + str(placement)
                    + (
                        "st"
                        if placement == 1
                        else "nd"
                        if placement == 2
                        else "rd"
                        if placement == 3
                        else "th"
                    )
                    + " in their match!",
                    color=0x00FF00
                    if placement == 1
                    else 0xFFFF00
                    if placement <= 4
                    else 0xFF0000,
                )

                tft_embed.set_footer(
                    text=str(tft_minutes)
                    + " Minutes "
                    + str(tft_seconds)
                    + " Seconds"
                    + " - "
                    + utils.get_region(account["region"])
                    + " - "
                    + "Teamfight Tactics"
                )
                tft_embed.add_field(
                    name=(
                        tft_queueId
                        + " - "
                        + "Set "
                        + str((tft_match_data["info"]["tft_set_number"]))
                    ),
                    value=(
                        "Level "
                        + str(participantObj["level"])
                        + " - "
                        + "Survived to "
                        + str(stage1)
                        + "-"
                        + str(stage2)
                    ),
                    inline=False,
                )
                tft_embed.set_thumbnail(url=thumbnail_url)

                for channel in account["channel"]:
                    guild = client.get_guild(channel["Guild ID"])
                    channel = guild.get_channel(channel["Channel ID"])
                    await channel.send(embed=tft_embed)

        with open("riot_accounts.json", "w") as f:
            json.dump(riot_accounts, f, indent=4, default=list)
            print("Updated the Riot account")
        await asyncio.sleep(20)


# @client.slash_command()
# async def last_game(
#     interaction: nextcord.Interaction,
#     summoner_name: str,
##     region: str = SlashOption(
#         name="region",
#         description="Please pick a region",
#         choices={
#             "EUW": "euw1",
#             "NA": "na1",
#             "EUNE": "eun1",
#             "KR": "kr",
#             "JP": "jp1",
#             "OCE": "oc1",
#             "BR": "br1",
#             "LAN": "la1",
#             "LAS": "la2",
#             "RU": "ru",
#             "TR": "tr1",
#         },
#     ),


# ):
#     user = None
#     for account in riot_accounts:
#         if account["summoner_name"] == summoner_name and account["region"] == region:
#             user = account

#     if user:
#         await interaction.send(embed=embed)
#     else:
#         await interaction.response.send_message("This user is not linked")

client.run(os.getenv("TOKEN"))
