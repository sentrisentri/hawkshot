import requests
import os


testingserverid = 1066097924653723848
headers = {"X-Riot-Token": os.getenv("API_KEY")}



tft_game_modes = {
    1101: "Normal",
    1100: "Ranked",
    1102: "TFT Tutorial",
    1130: "Hyper Roll",
    1160: "Double Up",

}


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
    tft_match_response = requests.get(tft_match_url, headers=headers)
    
    if tft_match_response.status_code == 200:
        tft_match_data = tft_match_response.json()
        return tft_match_data
    else:
        return None

async def get_match_ids(puuid, region):
    routing = get_routing(region)
    match_url = (
        f"https://{routing}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
    )
    match_response = requests.get(match_url, headers=headers)

    if match_response.status_code == 200:
        match_data = match_response.json()
        return match_data
    else:
        return None
    
async def get_tft_match_data(tft_match_id, region):
    routing = get_routing(region)
    tft_match_url = f"https://{routing}.api.riotgames.com/tft/match/v1/matches/{tft_match_id}"
    tft_match_response = requests.get(tft_match_url, headers=headers)

    if tft_match_response.status_code == 200:
        tft_match_data = tft_match_response.json()
        return tft_match_data
    else:
        return None






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

async def get_game_mode(game_mode):
    url = ("https://static.developer.riotgames.com/docs/lol/queues.json")
    gamemode_response = requests.get(url)
    gamemode_response.json()

def get_region(region):
    return region_names.get(region)

async def get_map_name(map_id):
    return map_names.get(map_id, "map name")


async def get_tft_game_mode(tft_game_mode):
    return tft_game_modes.get(tft_game_mode, "game mode")