from fastapi import FastAPI, HTTPException, Request, Query
from pydantic import BaseModel
from bs4 import BeautifulSoup
import requests
from pymongo import MongoClient
import time
from enum import Enum
import math
from goose3 import Goose

class Database(Enum):
    CLIENT = MongoClient('mongodb://localhost:27017/')
    DB = CLIENT.scraped_data
    COLLECTION = DB.web_data
    EXTRACTED_COLLECTION = DB.extracted_data

app = FastAPI()

class Item(BaseModel):
    search: str
class PaginationRequest(BaseModel):
    page_num: int
    page_size: int
   


def fetch_google_results(query):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        url = f"https://www.google.com/search?q={query}"
        response = requests.get(url, headers=headers)
        time.sleep(2)

        soup = BeautifulSoup(response.text, 'html.parser')
        results = []

        for g in soup.find_all('div', class_='tF2Cxc'):
            link = g.find('a')['href']
            result_text_element = g.find('div', class_='VwiC3b yXK7lf lVm3ye r025kc hJNv6b Hdw6tb')
            result_text = result_text_element.text if result_text_element else None 
            results.append({'link': link, 'result_text': result_text})

            if len(results) >= 10:
                break

        return results
    except Exception as e:
        print(f"Error fetching Google results: {e}")
        return []
def scrape_website(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        title = soup.title.text.strip() if soup.title else None
        meta_tags = {}
        for tag in soup.find_all('meta'):
            if tag.get('name'):
                meta_tags[tag.get('name').lower()] = tag.get('content')
            elif tag.get('property'):
                meta_tags[tag.get('property').lower()] = tag.get('content')
        seo_description = meta_tags.get('description', None)
        paragraphs = {f"paragraph_{i}": p.text.strip() for i, p in enumerate(soup.find_all('p'))}
        links = {f"link_{i}": a['href'] for i, a in enumerate(soup.find_all('a', href=True))}
        if not links:
            links = {'no_links_found': 'No links found on this page'}
        headers = {tag.name: tag.text.strip() for tag in soup.find_all(['h1', 'h2', 'h3'])}
        images = {f"image_{i}": img['src'] for i, img in enumerate(soup.find_all('img', src=True))}
        lists = {}
        for i, ul in enumerate(soup.find_all('ul')):
            lists[f"ul_{i}"] = [li.text.strip() for li in ul.find_all('li')]
        for i, ol in enumerate(soup.find_all('ol')):
            lists[f"ol_{i}"] = [li.text.strip() for li in ol.find_all('li')]
        tables = {}
        for table in soup.find_all('table'):
            header_row = table.find('tr')
            headers = [th.text.strip() for th in header_row.find_all('th')] if header_row else None
            
            rows_data = []
            for row in table.find_all('tr')[1:]:  
                columns = row.find_all(['th', 'td'])
                if headers and len(columns) == len(headers):  
                    row_data = {headers[idx]: column.text.strip() for idx, column in enumerate(columns)}
                else:
                    row_data = {'default_{idx}': column.text.strip() for idx, column in enumerate(columns)}
                rows_data.append(row_data)
            
            table_caption = table.caption.text.strip() if table.caption else 'Table'
            tables[table_caption] = rows_data
                
        data = {
            "url": url,
            "title": title,
            "seo_description": seo_description,
            "meta_tags": meta_tags,
            "paragraphs": paragraphs,
            "links": links,
            "headers": headers,
            "images": images,
            "lists": lists,
            "tables": tables
        }
        
        return data
    
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return None
def extract_title_and_text(url):
    try:
        g = Goose()
        article = g.extract(url=url)
        return {
            "url": url,
            "title": article.title,
            "body_text": article.cleaned_text
        }
    except Exception as e:
        print(f"Error extracting data from {url}: {e}")
        return None 

@app.post("/scrape/")
async def scrape_url(request: Request):
    try:
        body = await request.json()  
        search_term = body.get('search')

        if not search_term:
            raise HTTPException(status_code=400, detail="Search term field is required")

        query = search_term
        results = fetch_google_results(query)
        website_data_list = []

        for result in results:
            url = result['link']
            existing_data = Database.COLLECTION.value.find_one({"url": url})
            if existing_data:
                print(f"Skipping {url}, already scraped.")
                continue

            print(f"Scraping {url}")
            website_data = scrape_website(url)
            if website_data:
                website_data['result_text'] = result['result_text']
                website_data_list.append(website_data)

            time.sleep(1)

        if website_data_list:
            insert_result = Database.COLLECTION.value.insert_many(website_data_list)
            inserted_ids = [str(website_data['_id']) for website_data in website_data_list]
            for i in range(len(website_data_list)):
                website_data_list[i]['_id'] = inserted_ids[i]

        return website_data_list

    except Exception as e:
        print(f"Error in scrape_url: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
   
    

@app.post("/data/")
async def get_data(request: PaginationRequest):
    page = request.page_num
    size = request.page_size
    try:
        total_data = Database.COLLECTION.value.count_documents({})
        total_pages = math.ceil(total_data / size)
        
        if page > total_pages:
            raise HTTPException(status_code=400, detail="Page number out of range")

        data = list(Database.COLLECTION.value.find().skip((page - 1) * size).limit(size))
        for item in data:
            item['_id'] = str(item['_id'])  # Convert ObjectId to string

        return {
            "total_data": total_data,
            "total_pages": total_pages,
            "page_num": page,
            "data": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.post("/extract/")
async def extract_from_google(request: Request):
    try:
        body = await request.json()
        search_term = body.get('search')

        if not search_term:
            raise HTTPException(status_code=400, detail="Search term field is required")

        query = search_term
        google_results = fetch_google_results(query)
        all_extracted_data = []

        for result in google_results:
            url = result['link']
            existing_data = Database.EXTRACTED_COLLECTION.value.find_one({"url": url})

            if existing_data:
                print(f"Already scraped {url}. Retrieving from database.")
                existing_data['_id'] = str(existing_data['_id'])  # Convert ObjectId to string for response
                all_extracted_data.append(existing_data)
                continue

            print(f"Scraping {url}")
            extracted_data = extract_title_and_text(url)
            if extracted_data:
                Database.EXTRACTED_COLLECTION.value.insert_one(extracted_data)
                extracted_data['_id'] = str(extracted_data['_id'])  # Convert ObjectId to string for response
                all_extracted_data.append(extracted_data)

        return all_extracted_data

    except Exception as e:
        print(f"Error in extract_from_google: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/")
async def root():
    return {"message": "Welcome to the web scraping API. Use POST /scrape/ to scrape a URL."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
