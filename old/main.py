from typing import Dict, Optional

import requests


def get_application_token(
    client_id: str,
    client_secret: str,
    user_agent: str = "MyApp/1.0 (my-app-feedback@example.com)",
    host: str = "hh.ru",
    locale: str = "RU",
) -> Dict[str, Optional[str]]:
    """
    Получение access_token для приложения hh.ru

    Args:
        client_id: Идентификатор приложения (из личного кабинета разработчика)
        client_secret: Секретный ключ приложения
        user_agent: Название приложения и контактная почта в формате "AppName/Version (email)"
        host: Доменное имя сайта (по умолчанию hh.ru)
        locale: Идентификатор локали (по умолчанию RU)

    Returns:
        Словарь с токеном и метаданными или ошибкой

    Примечание:
        - Токен имеет неограниченный срок жизни
        - При повторном запросе старый токен отзывается
        - Запрашивать токен можно не чаще 1 раза в 5 минут
    """
    url = "https://api.hh.ru/token"

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "HH-User-Agent": user_agent,
    }

    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "host": host,
        "locale": locale,
    }

    try:
        response = requests.post(url, headers=headers, data=data, timeout=10)
        response.raise_for_status()

        token_data = response.json()
        return {
            "success": True,
            "access_token": token_data.get("access_token"),
            "token_type": token_data.get("token_type"),
            "expires_in": token_data.get(
                "expires_in"
            ),  # Для приложения обычно null/отсутствует
        }

    except requests.exceptions.HTTPError:
        error_data = response.json() if response.content else {}
        return {
            "success": False,
            "error": f"HTTP {response.status_code}",
            "details": error_data.get("errors", error_data),
            "description": error_data.get("description"),
        }
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": "Request failed", "details": str(e)}


# Пример использования
if __name__ == "__main__":
    # ВСТАВЬТЕ СВОИ СЕКРЕТЫ ЗДЕСЬ
    CLIENT_ID = "PC1JCC77M8707UGQ4NPQK31P7CT4T8MK2HL61QABANE9J7POHS1GDNTC78SRJMCB"
    CLIENT_SECRET = "PJCS60M220HSBI0H1TKFRCS7PVOCD2QF69AKROHM2LVIRPHOFGOV06NBHPVN2H4U"
    USER_AGENT = "AlfaHRService/1.0 (hr-service@alfabank.by)"

    result = get_application_token(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        user_agent=USER_AGENT,
        host="hh.ru",
        locale="RU",
    )

    if result["success"]:
        print("✅ Токен успешно получен:")
        print(f"   Access Token: {result['access_token']}")
        print("\n⚠️  ВАЖНО: сохраните этот токен в безопасном месте!")
        print("   При следующем запросе текущий токен будет отозван.")
    else:
        print(f"❌ Ошибка получения токена: {result['error']}")
        if result.get("details"):
            print(f"   Детали: {result['details']}")
