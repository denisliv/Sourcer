import requests
from tqdm import tqdm

ACCESS_TOKEN = "USERIBM3S8OHEFTBLSG29JV1R2QOTNGRCV7IGI4R76K597MFIMVUJ9JR58LO8K86"

number_of_pages = 2
per_page = 50
headers = {
    "HH-User-Agent": "AlfaHRService (alfa-hr-service@alfabank.by)",
    "Authorization": f"Bearer {ACCESS_TOKEN}",
}

job = "Python developer"
areas = [16]
data = []
for area in areas:
    for i in tqdm(range(number_of_pages)):
        url = "https://api.hh.ru/resumes"
        if area == 16:
            host = "rabota.by"
        else:
            host = "hh.ru"
        # par = {
        #     "host": host,
        #     "text": job,
        #     "text.logic": "all",
        #     "text.field": "title", # title, skills, experience_position
        #     "text.period": "",
        #     "experience": "between3And6", # noExperience, between1And3, between3And6, moreThan6
        #     "text": "junior",
        #     "text.logic": "except",
        #     "text.field": "title", # title, skills, experience_position
        #     "text.period": "",
        #     "period": 30,
        #     "area": area,
        #     "per_page": "10",
        #     "page": i,
        # }
        par = [
            ("host", host),
            ("text", job),
            ("text.logic", "all"),
            ("text.field", "title"),  # title, skills, experience_position
            ("text.period", ""),
            (
                "experience",
                "between3And6",
            ),  # noExperience, between1And3, between3And6, moreThan6
            ("text", "junior"),
            ("text.logic", "except"),
            ("text.field", "title"),  # title, skills, experience_position
            ("text.period", ""),
            ("period", 30),
            ("area", area),
            ("per_page", per_page),
            ("page", i),
        ]
        r = requests.get(url, params=par, headers=headers)
        e = r.json()
        data.append(e)
