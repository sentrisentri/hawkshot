import requests
import os
from dotenv import load_dotenv

load_dotenv()

headers = {"X-Riot-Token": os.getenv("API_KEY")}
tft_headers = {"X-Riot-Token": os.getenv("TFT_API_KEY")}

routings = {
    "br1": "americas",
    "eun1": "europe",
    "euw1": "europe",
    "jp1": "asia",
    "kr": "asia",
    "la1": "americas",
    "la2": "americas",
    "na1": "americas",
    "oc1": "sea",
    "tr1": "europe",
    "ru": "europe",
    "ph2": "sea",
    "sg2": "sea",
    "tw2": "sea",
    "vn2": "sea",
    "th2": "sea",
}

region_names = {
    "br1": "Brazil",
    "eun1": "Europe Nordic & East",
    "euw1": "Europe West",
    "jp1": "Japan",
    "kr": "Korea",
    "la1": "Latin America North",
    "la2": "Latin America South",
    "na1": "North America",
    "oc1": "Oceania",
    "tr1": "Turkey",
    "ru": "Russia",
    "ph2": "Philippines",
    "sg2": "Singapore",
    "tw2": "Taiwan",
    "vn2": "Vietnam",
    "th2": "Thailand",
}

async def get_tft_match_ids(puuid, region):
    routing = get_routing(region)
    tft_match_url = (
        f"https://{routing}.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids"
    )
    tft_match_response = requests.get(tft_match_url, headers=tft_headers)
    tft_match_ids_json = tft_match_response.json()
    
    if len(tft_match_ids_json) == 0:
        return None
    
    if tft_match_response.status_code == 200:
        return tft_match_ids_json
    else:
        return None

async def get_match_ids(puuid, region):
    routing = get_routing(region)
    match_url = (
        f"https://{routing}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
    )
    match_response = requests.get(match_url, headers=headers)
    match_ids_json = match_response.json()

    if len(match_ids_json) == 0:
        return None

    if match_response.status_code == 200:
        return match_ids_json
    else:
        return None
    
async def get_tft_match_data(tft_match_id, region):
    routing = get_routing(region)
    tft_match_url = f"https://{routing}.api.riotgames.com/tft/match/v1/matches/{tft_match_id}"
    tft_match_response = requests.get(tft_match_url, headers=tft_headers)

    if tft_match_response.status_code == 200:
        tft_match_data = tft_match_response.json()
        return tft_match_data
    else:
        return None


async def get_summoner_id(summoner_name, region):
    summoner_url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{summoner_name}"
    summoner_response = requests.get(summoner_url, headers=headers)

    if summoner_response.status_code == 200:
        summoner_data = summoner_response.json()
        return summoner_data["id"]
    else:
        print(summoner_response.json())
        return None
    
async def get_tft_puuid(summoner_name, region):
    tftpuuid_url = f"https://{region}.api.riotgames.com/tft/summoner/v1/summoners/by-name/{summoner_name}"
    tftpuuid_response = requests.get(tftpuuid_url, headers=tft_headers)
    
    if tftpuuid_response.status_code == 200:
        tftpuuid_data = tftpuuid_response.json()
        return tftpuuid_data["puuid"]
    else:
        print(tftpuuid_response.json())
        return None
    
async def get_solo_summoner_rank(summoner_name, region):
    summoner_id = await get_summoner_id(summoner_name, region)
    ranking_url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}"
    ranking_response = requests.get(ranking_url, headers=headers)
    solorank = None
    if ranking_response.status_code == 200:
        ranking_data = ranking_response.json()
        for queue in ranking_data:
            if queue["queueType"] == "RANKED_SOLO_5x5":
                solorank = queue
                break
            else:
                solorank = "Unranked"
        
        if solorank == None:
            solorank = "Unranked"            
        
        if solorank == "Unranked":
            return solorank
        else:
            return solorank["tier"].capitalize() + " " + solorank["rank"] + " " + str(solorank["leaguePoints"]) + " LP"
        
        
        
async def get_flex_summoner_rank(summoner_name, region):
    summoner_id = await get_summoner_id(summoner_name, region)
    ranking_url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}"
    ranking_response = requests.get(ranking_url, headers=headers)
    flexrank = None
    if ranking_response.status_code == 200:
        ranking_data = ranking_response.json()
        for queue in ranking_data:
            if queue["queueType"] == "RANKED_FLEX_SR":
                flexrank = queue
                break
            else:
                flexrank = "Unranked"
                    
        if flexrank == None:
            flexrank = "Unranked"
            
        if flexrank == "Unranked":
            return flexrank
        else:
            return flexrank["tier"].capitalize() + " " + flexrank["rank"] + " " + str(flexrank["leaguePoints"]) + " LP"


async def get_tft_summoner_id(summoner_name, region):
    summoner_url = f"https://{region}.api.riotgames.com/tft/summoner/v1/summoners/by-name/{summoner_name}"
    summoner_response = requests.get(summoner_url, headers=tft_headers)

    if summoner_response.status_code == 200:
        summoner_data = summoner_response.json()
        return summoner_data["id"]
    else:
        print(summoner_response.json())
        return None

async def get_tft_summoner_rank(summoner_name, region):
    tft_summoner_id = await get_tft_summoner_id(summoner_name, region)
    ranking_url = f"https://{region}.api.riotgames.com/tft/league/v1/entries/by-summoner/{tft_summoner_id}"
    ranking_response = requests.get(ranking_url, headers=tft_headers)
    flexrank = None
    if ranking_response.status_code == 200:
        ranking_data = ranking_response.json()
        for queue in ranking_data:
            if queue["queueType"] == "RANKED_TFT":
                flexrank = queue
                break
            else:
                flexrank = "Unranked"
                    
        
        if flexrank == "Unranked" or flexrank == None:
            return "Unranked"
        else:
            return (flexrank["tier"]).capitalize() + " " + flexrank["rank"] + " " + str(flexrank["leaguePoints"]) + " LP"
       
async def get_highest_champion_mastery_id(summoner_name, region):
    summonerid = await get_summoner_id(summoner_name, region)
    mastery_url = f"https://{region}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-summoner/{summonerid}"
    mastery_response = requests.get(mastery_url, headers=headers)
    highest_champ = None
    if mastery_response.status_code == 200:
        mastery_data = mastery_response.json()
        highest_champ = mastery_data[0]
        return await champid_to_name(highest_champ["championId"])
    
    
async def champid_to_name(id):
    id_url = f"https://cdn.communitydragon.org/latest/champion/{id}/data"
    id_response = requests.get(id_url)
    return id_response.json()["name"]
       
async def get_summoner_icon(summoner_name, region):
    icon_url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{summoner_name}"
    icon_response = requests.get(icon_url, headers=headers)
    return icon_response.json()["profileIconId"]

async def get_summoner_level(summoner_name, region):
    icon_url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{summoner_name}"
    icon_response = requests.get(icon_url, headers=headers)
    print(icon_response.json()["summonerLevel"])
    return icon_response.json()["summonerLevel"]

async def get_match_data(match_id, region):
    routing = get_routing(region)
    match_url = f"https://{routing}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    match_response = requests.get(match_url, headers=headers)

    if match_response.status_code == 200:
        match_data = match_response.json()
        return match_data
    else:
        return None
 
 


 
   
def get_routing(region):
    return routings.get(region)


def get_region(region):
    return region_names.get(region)



