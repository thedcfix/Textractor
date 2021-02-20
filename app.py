import flask
from flask import Flask, flash, redirect, request, render_template, session, url_for
import os
import requests
from readability import Document
import html2text
from azure.cosmos import exceptions, CosmosClient, PartitionKey
from urllib.parse import urlparse
import hashlib
import re
from azure.ai.textanalytics import TextAnalyticsClient
from azure.core.credentials import AzureKeyCredential

app = flask.Flask(__name__, static_url_path='/assets')

# Initialize the Cosmos client
endpoint = "YOUR_COSMOS_ENDPOINT"
key = 'YOUR_COSMOS_API_KEY'

# <create_cosmos_client>
client = CosmosClient(endpoint, key)
database_name = 'YOUR_DB_NAME'
container_name = 'YOU_CONTAINER_NAME'

db = client.get_database_client(database_name)
container = db.get_container_client(container_name)

# text analytics
analytics_endpoint = "YOUR_TEXT_ANALYTICS_ENDPOINT"
analytics_key = "YOUR_TEXT_ANALYTICS_API_KEY"

def authenticate_client():
    ta_credential = AzureKeyCredential(analytics_key)

    text_analytics_client = TextAnalyticsClient(
            endpoint=analytics_endpoint, 
            credential=ta_credential, 
            api_version='v3.0')
	
    return text_analytics_client

# creating the text analytics client
analytics_client = authenticate_client()

def fix_text_length(text):
    
    text = str(text)
    final = ''
    # maximum text length supported by the analytics service
    max_len = 5120
    
    if (len(text) > max_len):
        chunks = text.split('.')
        
        for chunk in chunks:
            if len(final) + len(chunk) < max_len:
                final = final + "." + chunk
    else:
        final = str(text)
    
    return final

def sentiment_analysis(client, text):

    text = fix_text_length(text)
    
    documents = [text]
    response = client.analyze_sentiment(documents = documents)[0]

    sentiment = response.sentiment
    positive_score = response.confidence_scores.positive
    neutral_score = response.confidence_scores.neutral
    negative_score = response.confidence_scores.negative

    outcome =     {    'sentiment': sentiment,
                    'positive_score': positive_score,
                    'neutral_score': neutral_score,
                    'negative_score': negative_score
                }
    
    return outcome

def key_phrase_extraction(client, text):

    keywords = []
    
    text = fix_text_length(text)
    
    documents = [text]
    response = client.extract_key_phrases(documents = documents)[0]

    if not response.is_error:
        for phrase in response.key_phrases:
            keywords.append(phrase)
    
    return keywords

# inserting data into the DB
def insert_in_db(analytics_client, container, url, title, article):

	website = urlparse(url)
	id = hashlib.sha512(url.encode()).hexdigest()

	try:

		title_sentiment = sentiment_analysis(analytics_client, title)
		article_sentiment = sentiment_analysis(analytics_client, article)

		keywords_title = key_phrase_extraction(analytics_client, title)
		keywords_article = key_phrase_extraction(analytics_client, article)

		article = 	{  	'id' : id,
						'url' : url,
						'website' : website.netloc,
						'title' : title,
						'article' : article,
						'title_sentiment': title_sentiment,
						'article_sentiment': article_sentiment,
						'keywords_title': keywords_title,
						'keywords_article': keywords_article
					}

		container.upsert_item(article)
	
	except:
		print("There has been a mega failure somewhere :(")

def fix_article(article):
	article = article.replace('\\', '')

	article = ' '.join(article.split())
	article = article.replace('> -', '<br/> * ')

	article = article.replace('>', '')
	article = article.replace('<br/', '<br/>')

	article = article.replace('\n', '')
	article = ' '.join(article.split())

	article = article.replace(' * ', '<br/> * ')

	return article

@app.route('/')
def index():
	return flask.render_template('index.html')

@app.route('/index.html')
def home():
	return flask.render_template('index.html')

@app.route('/', methods=['POST'])
def extract():
	
	url = request.form['site']

	response = requests.get(url)
	doc = Document(response.text)

	parser = html2text.HTML2Text()
	parser.ignore_links = True
	parser.ignore_images = True
	parser.ignore_emphasis = True
	parser.ignore_anchors = True
	parser.ignore_tables = True

	title = doc.title()
	title = re.sub(r' *- [-a-zA-Z0-9 @:%._\+~#=]{1,256}', '', title)														#	<---- this crops everything after -[space]
	title = re.sub(r' *- *[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)', '', title)	#	<---- this is for websites only
	article = parser.handle(str(doc.summary()))
	article = fix_article(article)
	article = article.split("<br/>")

	if url != '':
		insert_in_db(analytics_client, container, url, title, article)
		return flask.render_template('index.html', title=title, data=article)
	else:
		error_msg = "Enter a valid URL"
		return flask.render_template('index.html', error=error_msg)

port = int(os.getenv('PORT', '5000'))

if __name__ == "__main__":
	app.run(host='0.0.0.0', port=int(port))