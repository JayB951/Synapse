import os
import sys
import requests


def main():
    print("===================================")
    print("SYNAPSE – adatbázis-kapcsolat teszt")
    print("===================================")

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SECRET_KEY")

    if not supabase_url or not supabase_key:
        print("HIBA: Hiányzó Supabase kapcsolati adat.")
        print("Szükséges GitHub Secrets:")
        print("- SUPABASE_URL")
        print("- SUPABASE_SECRET_KEY")
        sys.exit(1)

    endpoint = (
        f"{supabase_url.rstrip('/')}"
        "/rest/v1/sources?select=id,name&limit=5"
    )

    headers = {
        "apikey": supabase_key,
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(
            endpoint,
            headers=headers,
            timeout=20
        )

        if response.status_code == 200:
            print("SIKER: A SYNAPSE elérte a Supabase adatbázist.")
            print("A források száma:", len(response.json()))
            print("Kapcsolat rendben.")
        else:
            print("HIBA: A Supabase nem fogadta el a kérést.")
            print("HTTP státuszkód:", response.status_code)
            print("Válasz:", response.text[:500])
            sys.exit(1)

    except requests.exceptions.RequestException as error:
        print("HIBA: Nem sikerült csatlakozni.")
        print("Részletek:", str(error))
        sys.exit(1)


if __name__ == "__main__":
    main()
