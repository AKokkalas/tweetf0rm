# -*- coding: utf-8 -*-

from exceptions import MissingArgs
import util
import twython
import re
import datetime
import json
import time
import os
import logging
import logging.handlers

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG,
                    format='(%(asctime)s) [%(process)d] %(levelname)s: %(message)s')
requests_log = logging.getLogger("requests")
requests_log.setLevel(logging.WARNING)


MAX_RETRY_CNT = 3
WAIT_TIME = 30


class TwitterCrawler(twython.Twython):

    def __init__(self, *args, **kwargs):
        """
        Constructor with apikeys, and output folder

        * apikeys: apikeys
        """
        import copy

        apikeys = copy.copy(kwargs.pop('apikeys', None))

        if not apikeys:
            raise MissingArgs('apikeys is missing')

        self.apikeys = copy.copy(apikeys)  # keep a copy
        #self.crawler_id = kwargs.pop('crawler_id', None)

        self.output_folder = kwargs.pop('output_folder', './data')
        if not os.path.exists(self.output_folder):
            os.makedirs(self.output_folder)

        # default to use oauth2 (application level access, read-only)
        oauth2 = kwargs.pop('oauth2', True)

        if oauth2:
            # no need for these in oauth2
            apikeys.pop('oauth_token')
            apikeys.pop('oauth_token_secret')
            twitter = twython.Twython(
                apikeys['app_key'], apikeys['app_secret'], oauth_version=2)
            access_token = twitter.obtain_access_token()
            kwargs['access_token'] = access_token
            apikeys.pop('app_secret')
        else:
            # api needs a user context
            pass

        kwargs.update(apikeys)

        super(TwitterCrawler, self).__init__(*args, **kwargs)

    def rate_limit_error_occured(self, resource, api):
        rate_limits = self.get_application_rate_limit_status(resources=[
                                                             resource])

        # e.g., ['resources']['followers']['/followers/list']['reset']

        wait_for = int(rate_limits['resources'][resource]
                       [api]['reset']) - time.time() + WAIT_TIME

        # logger.debug(rate_limits)
        logger.warn('[%s] rate limit reached, sleep for %d' %
                    (rate_limits['rate_limit_context'], wait_for))
        if wait_for < 0:
            wait_for = 60

        time.sleep(wait_for)

    def geo_search(self, call='query', query=None):

        if not query:
            raise Exception("geo_search: query cannot be empty")

        now = datetime.datetime.now()

        day_output_folder = os.path.abspath(
            '%s/%s' % (self.output_folder, now.strftime('%Y%m%d')))

        if not os.path.exists(day_output_folder):
            os.makedirs(day_output_folder)

        filename = os.path.abspath(
            '%s/%s' % (day_output_folder, util.md5(query.encode('utf-8'))))

        retry_cnt = MAX_RETRY_CNT
        while retry_cnt > 0:
            try:

                result = None

                if ('query' == call):
                    result = self.search_geo(query=query)
                elif ('ip' == call):
                    result = self.search_geo(ip=query)
                else:
                    logger.error("call == ('query' or 'ip')")
                    return

                if (result):
                    with open(filename, 'a+', newline='', encoding='utf-8') as f:
                        f.write('%s\n' % json.dumps(result))

                time.sleep(1)

                return False

            except twython.exceptions.TwythonRateLimitError:
                self.rate_limit_error_occured('geo', '/geo/search')
            except Exception as exc:
                time.sleep(10)
                logger.error(
                    "exception: %s; when fetching place: %s" % (exc, query))
                retry_cnt -= 1
                if (retry_cnt == 0):
                    logger.warn("exceed max retry... return")
                    return

        return

    def fetch_users(self, call='screen_name', users=[]):
        '''
        call: /users/lookup
        '''
        if not users:
            raise Exception("users/lookup: users cannot be empty")

        if len(users) > 100:
            raise Exception("users/lookup: users cannot exceed 100 elements")

        now = datetime.datetime.now()

        filename = os.path.abspath(
            '%s/%s' % (self.output_folder, now.strftime('%Y%m%d%H%M%S')))

        retry_cnt = MAX_RETRY_CNT
        while retry_cnt > 0:
            try:

                if (call == 'screen_name'):
                    result = self.lookup_user(
                        screen_name=",".join(str(x) for x in users))
                elif (call == 'user_id'):
                    result = self.lookup_user(
                        user_id=",".join(str(x) for x in users))
                else:
                    logger.error("call == ('screen_name' or 'user_id')")
                    return

                if (result):

                    with open(filename, 'a+', newline='', encoding='utf-8') as f:
                        f.write('%s\n' % json.dumps(result))

                        retry_cnt = 0

                time.sleep(1)

            except twython.exceptions.TwythonRateLimitError:
                self.rate_limit_error_occured('users', '/users/lookup')
            except Exception as exc:
                time.sleep(10)
                logger.error("exception: %s; when fetching users" % (exc))
                retry_cnt -= 1
                if (retry_cnt == 0):
                    logger.warn("exceed max retry... return")
                    return

        return

    def fetch_user_relationships(self, call='/friends/ids', user_id=None):
        '''
        call: /friends/ids, /friends/list, /followers/ids, and /followers/list
        '''
        if not user_id:
            raise Exception("user_relationship: user_id cannot be None")

        now = datetime.datetime.now()

        day_output_folder = os.path.abspath(
            '%s/%s' % (self.output_folder, now.strftime('%Y%m%d')))

        if not os.path.exists(day_output_folder):
            os.makedirs(day_output_folder)

        filename = os.path.abspath('%s/%s' % (day_output_folder, user_id))

        with open(filename, 'w') as f:
            pass

        cursor = -1

        cnt = 0

        retry_cnt = MAX_RETRY_CNT
        while cursor != 0 and retry_cnt > 0:
            try:
                result = None
                if (call == '/friends/ids'):
                    result = self.get_friends_ids(
                        user_id=user_id, cursor=cursor, count=5000)
                    cnt += len(result['ids'])
                elif (call == '/friends/list'):
                    result = self.get_friends_list(
                        user_id=user_id, cursor=cursor, count=200)
                    cnt += len(result['users'])
                elif (call == '/followers/ids'):
                    result = self.get_followers_ids(
                        user_id=user_id, cursor=cursor, count=5000)
                    cnt += len(result['ids'])
                elif (call == '/followers/list'):
                    result = self.get_followers_list(
                        user_id=user_id, cursor=cursor, count=200)
                    cnt += len(result['users'])

                if (result):

                    cursor = result['next_cursor']

                    with open(filename, 'a+', newline='', encoding='utf-8') as f:
                        f.write('%s\n' % json.dumps(result))

                time.sleep(1)

            except twython.exceptions.TwythonRateLimitError:
                resource_family = None
                m = re.match(r'^\/(?P<resource_family>.*?)\/', call)
                if (m):
                    resource_family = m.group('resource_family')

                self.rate_limit_error_occured(resource_family, call)
            except Exception as exc:
                time.sleep(10)
                logger.error(
                    "exception: %s; when fetching user_id: %d" % (exc, user_id))
                retry_cnt -= 1
                if (retry_cnt == 0):
                    logger.warn("exceed max retry... return")
                    return

        logger.info("[%s] total [%s]: %d; " % (user_id, call, cnt))
        return

    def fetch_retweets(self, tweet_id=None, now=datetime.datetime.now()):
        '''
        call: /friends/ids, /friends/list, /followers/ids, and /followers/list
        '''
        # print(type(tweet_id))

        if not tweet_id:
            raise Exception("retweet: retweet_id cannot be None")

        retweet_ids = set()

        day_output_folder = os.path.abspath(
            '%s/%s' % (self.output_folder, now.strftime('%Y%m%d')))

        if not os.path.exists(day_output_folder):
            os.makedirs(day_output_folder)

        filename = os.path.abspath('%s/%s' % (day_output_folder, tweet_id))

        with open(filename, 'w') as f:
            pass
        retry_cnt = MAX_RETRY_CNT
        while retry_cnt > 0:
            try:
                result = self.get_retweets(id=tweet_id, count=100, trim_user=1)
                logger.info("find %d retweets of [%d]" % (
                    len(result), tweet_id))
                for tweet in result:
                    retweet_ids.add(tweet['id'])

                if(len(result) > 0):
                    with open(filename, 'a+', newline='', encoding='utf-8') as f:

                        f.write('%s\n' % json.dumps(result))

                time.sleep(1)

                return False, retweet_ids

            except twython.exceptions.TwythonRateLimitError:
                self.rate_limit_error_occured(
                    'statuses', '/statuses/retweets/:id')
            except Exception as exc:
                time.sleep(10)
                logger.error(
                    "exception: %s; when fetching tweet_id: %d" % (exc, tweet_id))
                retry_cnt -= 1
                if (retry_cnt == 0):
                    logger.warn("exceed max retry... return")
                    return False, retweet_ids

        return False, retweet_ids

    def fetch_user_timeline(self, user_id=None, since_id=1):

        if not user_id:
            raise Exception("user_timeline: user_id cannot be None")

        now = datetime.datetime.now()
        day_output_folder = os.path.abspath(
            '%s/%s' % (self.output_folder, now.strftime('%Y%m%d')))

        if not os.path.exists(day_output_folder):
            os.makedirs(day_output_folder)

        filename = os.path.abspath('%s/%s' % (day_output_folder, user_id))

        prev_max_id = -1
        current_max_id = 0
        current_since_id = since_id

        cnt = 0

        retry_cnt = MAX_RETRY_CNT
        while (current_max_id != prev_max_id and retry_cnt > 0):
            try:
                if current_max_id > 0:
                    tweets = self.get_user_timeline(
                        user_id=user_id, tweet_mode='extended', since_id=since_id, max_id=current_max_id - 1, count=200)
                else:
                    tweets = self.get_user_timeline(
                        user_id=user_id, tweet_mode='extended', since_id=since_id, count=200)

                # if no new tweets are found, the prev_max_id will be the same as current_max_id
                prev_max_id = current_max_id

                with open(filename, 'a+', newline='', encoding='utf-8') as f:
                    for tweet in tweets:
                        f.write('%s\n' % json.dumps(tweet))
                        if current_max_id == 0 or current_max_id > int(tweet['id']):
                            current_max_id = int(tweet['id'])
                        if current_since_id == 0 or current_since_id < int(tweet['id']):
                            current_since_id = int(tweet['id'])

                # no new tweets found
                if (prev_max_id == current_max_id):
                    break

                cnt += len(tweets)
                time.sleep(1)

            except twython.exceptions.TwythonRateLimitError:
                self.rate_limit_error_occured(
                    'statuses', '/statuses/user_timeline')
            except Exception as exc:
                time.sleep(10)
                logger.error(
                    "exception: %s; when fetching user_id: %d" % (exc, user_id))
                retry_cnt -= 1
                if (retry_cnt == 0):
                    logger.warn("exceed max retry... return")
                    return since_id, True  # REMOVE the user from the list of track

        logger.info("[%s] total tweets: %d; since_id: [%d]" %
                    (user_id, cnt, since_id))
        return current_since_id, False

    # ADDED search_name for finding it in mongoDB
    def search_by_query(self, query, since_id=0, geocode=None, search_name="no_search_name", lang=None, output_filename=None):
        start_time = time.time()

        # filter out retweets and replies
        query = "(" + query + ") " + "-filter:retweets"

        if not query:
            raise Exception("search: query cannot be None")

        now = datetime.datetime.now()
        logger.info("query: %s; since_id: %d" % (query, since_id))
        place = None
        geo = None

        if (geocode):
            place, geo = geocode

            day_output_folder = os.path.abspath(
                '%s/%s/%s' % (self.output_folder, now.strftime('%Y%m%d'), place))
        else:
            # ALEX HERE names the output folders
            day_output_folder = os.path.abspath(
                '%s/%s' % (self.output_folder, now.strftime('%Y%m%d')))

        if not os.path.exists(day_output_folder):
            os.makedirs(day_output_folder)

        # ALEX HERE names the output files | we can send back this code as id
        filename = os.path.abspath(
            '%s/%s' % (day_output_folder, util.md5(query.encode('utf-8'))))

        # logger.info("filename: %s; since_id: %d" % (filename, since_id))
        prev_max_id = -1
        MAX_NUM_OF_TWEETS = 10000
        current_max_id = 0
        cnt = 0
        current_since_id = since_id
        no_new_tweets = False

        retry_cnt = MAX_RETRY_CNT
        #result_tweets = []

        # Get the database ALEX
        from mongo_connector import get_database
        dbname = get_database()
        from pymongo import ASCENDING, errors
        from pymongo.write_concern import WriteConcern
        import calendar

        current_GMT = time.gmtime()

        while current_max_id != prev_max_id and retry_cnt > 0:
            try:
                if current_max_id > 0:
                    tweets = self.search(q=query, geocode=geo, since_id=since_id, lang=lang,
                                         tweet_mode='extended', max_id=current_max_id - 1, result_type='recent', count=100)
                else:
                    tweets = self.search(q=query, geocode=geo, since_id=since_id,
                                         lang=lang, tweet_mode='extended', result_type='recent', count=100)

                # if no new tweets are found, the prev_max_id will be the same as current_max_id
                prev_max_id = current_max_id

                # Save timestamp in article

                timestamp = calendar.timegm(current_GMT)

                # Change file with connection to mongoDB
                # Create a new collection
                collection_name = dbname["tweeter"]
                # item_details = collection_name.find()
                # create index
                index_name = 'tweetId_search_name_indx'
                if index_name not in collection_name.index_information():
                    collection_name.create_index([("id_str", ASCENDING), ("search_name", ASCENDING)], name=index_name,
                                                 unique=True)
                logger.info("time to crawl: %.3f seconds" % (time.time() -
                            start_time))

                insert_time = time.time()
                count, count_double = 0, 0
                for tweet in tweets['statuses']:

                    count += 1
                    # INSERT in mongodb
                    # logger.info("tweet id: %s" % (tweet))
                    #logger.info("tweet id: %s" % (tweet["id"]))
                    # tweet = tweet["retweeted_status"]
                    tweet["search_name"] = search_name  # "custom_search_name"
                    tweet["query"] = query
                    tweet["date_time"] = now
                    tweet["timestamp"] = timestamp
                    # collection_name.insert_one(tweet)
                    #collection_name.replace_one({"full_text": tweet["full_text"], "search_name" : search_name}, tweet, upsert=True )
                    # collection_name.replace_one(
                    #     {"full_text": tweet["full_text"]}, tweet, upsert=True)
                    try:
                        collection_name.insert_one(tweet)
                    except errors.DuplicateKeyError:
                        print(
                            'Dublicate key (twitter-collection), doc already exists in DB..skip..')
                        count_double += 1
                    if current_max_id == 0 or current_max_id > int(tweet['id']):
                        current_max_id = int(tweet['id'])
                    if current_since_id == 0 or current_since_id < int(tweet['id']):
                        current_since_id = int(tweet['id'])
                    # break

                logger.info("tweets added: %d / time2insert in DB: %.3f seconds" % (
                    count, (time.time() - insert_time)))

                # from pandas import DataFrame
                # convert the dictionary objects to dataframe
                # items_df = DataFrame(item_details)

                # see the magic
                # print(items_df)

                # for item in item_details:
                #
                #     logger.info(item['_id'])

                # with open(filename, 'a+', newline='', encoding='utf-8') as f:
                #     for tweet in tweets['statuses']:
                #         #logger.info("current_max_id: %s; tweets: %s"%(current_max_id, tweets))
                #         logger.info("current_max_id: %s"%(current_max_id))
                #         f.write('%s\n'%json.dumps(tweet))
                #         if current_max_id == 0 or current_max_id > int(tweet['id']):
                #             current_max_id = int(tweet['id'])
                #         if current_since_id == 0 or current_since_id < int(tweet['id']):
                #             current_since_id = int(tweet['id'])

                # no new tweets found

                if (prev_max_id == current_max_id or cnt >= MAX_NUM_OF_TWEETS):
                    no_new_tweets = True
                    # If last record insert dummy last record
                    collection_name = dbname["tweeter"]
                    insert_dummy_json = {}
                    insert_dummy_json['last_record'] = True
                    insert_dummy_json['search_name'] = search_name
                    insert_dummy_json['query'] = query  # add query search
                    insert_dummy_json['total_tweets_fetched'] = cnt
                    insert_dummy_json['prexisted_tweets'] = count_double
                    insert_dummy_json['date_time'] = now
                    insert_dummy_json['timestamp'] = timestamp

                    collection_name.insert_one(insert_dummy_json)

                    break

                # result_tweets.extend(tweets['statuses'])

                cnt += len(tweets['statuses'])

                # if (cnt % 1000 == 0):
                #     logger.info("[%d] tweets... "%cnt)

                # logger.info(cnt)

                #logger.debug('%d > %d ? %s'%(prev_max_id, current_max_id, bool(prev_max_id > current_max_id)))

                time.sleep(1)

            except twython.exceptions.TwythonRateLimitError:
                self.rate_limit_error_occured('search', '/search/tweets')
            except Exception as exc:
                time.sleep(10)
                logger.error("exception: %s" % exc)
                retry_cnt -= 1
                if (retry_cnt == 0):
                    logger.warn("exceed max retry... return")
                    return since_id
                    #raise MaxRetryReached("max retry reached due to %s"%(exc))

        logger.info("[%s]; since_id: [%d]; total tweets: %d " %
                    (query, since_id, cnt))

        return current_since_id, no_new_tweets

    def lookup_tweets_by_ids(self, tweet_ids=[]):

        if not tweet_ids:
            raise Exception("/statuses/lookup: tweet_ids cannot be None")

        if len(tweet_ids) > 100:
            raise Exception(
                "/statuses/lookup: tweet_ids cannot have more than 100 elements")

        now = datetime.datetime.now()

        # day_output_folder = os.path.abspath('%s/%s'%(self.output_folder, now.strftime('%Y%m%d')))

        # if not os.path.exists(day_output_folder):
        #     os.makedirs(day_output_folder)

        cnt = 0

        try:

            tweets = self.lookup_status(
                id=list(tweet_ids), tweet_mode="extended")
            cnt = len(tweets)
            if (cnt > 0):
                for tweet in tweets:
                    filename = os.path.abspath(
                        '%s/%s.json' % (self.output_folder, now.strftime('%Y%m%d')))
                    with open(filename, 'a+', newline='', encoding='utf-8') as f:
                        f.write('%s\n' % json.dumps(tweet))

        except twython.exceptions.TwythonRateLimitError:
            self.rate_limit_error_occured('statuses', '/statuses/lookup')
        except Exception as exc:
            time.sleep(10)
            logger.error(
                "exception: %s; when fetching [%s->%s]" % (exc, tweet_ids[0], tweet_ids[-1]))

        logger.info("total tweets: %s; [%s->%s]" %
                    (cnt, tweet_ids[0], tweet_ids[-1]))
