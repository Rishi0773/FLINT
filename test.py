from google import genai

API_KEY = "AQ.Ab8RN6K7i0xeRMb1VehgfdO50uX8HG46P88bzjUNvBju0sOT98-dDw"

client = genai.Client(api_key=API_KEY)
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="hello"
)
print(response.text)