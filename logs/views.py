import requests
import datetime
import json
from random import randint

from django.contrib.auth import get_user_model, login
from django.http import JsonResponse, HttpResponse
from django.utils.html import strip_tags
from rest_framework import viewsets, permissions
from django.views.decorators.cache import cache_page

from .models import Page, Metric
from .serializers import PageSerializer, MetricSerializer
from .IBMnlp import getIBMEmotions, getMoodScores, getEntityEmotions, parseEntityEmotions
from .amadeus import getPOIS


with open('static/prompts.json', 'r') as f:
    prompts = json.load(f)


class PageViewSet(viewsets.ModelViewSet):
    serializer_class = PageSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'date'

    def get_queryset(self):
        return Page.objects.filter(owner=self.request.user)


class MetricViewSet(viewsets.ModelViewSet):
    serializer_class = MetricSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'name'

    def get_queryset(self):
        return Metric.objects.filter(page__date=self.kwargs['page_date'], page__owner=self.request.user)


@cache_page(60)
def weather(request):
    resp = requests.get("http://api.openweathermap.org/data/2.5/weather?id=4931972&APPID=3a2410d61b7127eea64a08e1093fb82c")
    resp.raise_for_status()

    return JsonResponse(resp.json())

def entry(request):
    date = request.GET.get('date')
    page = Page.objects.get(date=date, owner=request.user)
    return JsonResponse({
        "content": page.content
    })

def mood(request):
    page = request.GET.get('page')
    if page is not None:
        page = Page.objects.get(date=page, owner=request.user)
        scores = getMoodScores(getIBMEmotions(page.content))
        scores = {k: round((v * 4) + 1) for k, v in scores.items()}
        for key, val in scores.items():
            Metric.objects.update_or_create(page=page, name=key.lower(), defaults={
                'value': val
            })
        return JsonResponse({
            'success': True,
            'scores': scores
        })

    text = request.GET.get('text')
    if not text:
        return JsonResponse({
            'success': False
        })
    return JsonResponse(getMoodScores(getIBMEmotions(text)))


def prompt(request):
    lastObj = request.GET.get("lastObj")
    lastSentiment = request.GET.get("lastSentiment")
    text = strip_tags(request.GET.get("text", "")).strip()
    if text:
        entities, emotion = getEntityEmotions(text)
        obj, sentiment = parseEntityEmotions(entities, emotion, lastObj, lastSentiment)
    else:
        obj = None
        sentiment = 'neutral'

    if obj is None:
        questions = prompts[sentiment]['no_arg']
        question = questions[randint(0, len(questions) - 1)]
    else:
        questions = prompts[sentiment]['arg']
        question = questions[randint(0, len(questions) - 1)].format(obj)

    return JsonResponse({
        "question": question,
        "lastObj": '' if obj is None else obj,
        "lastSentiment": sentiment
    })


def user(request):
    # TODO: actually implement auth
    if not request.user.is_authenticated:
        User = get_user_model()
        obj, _ = User.objects.get_or_create(
            username='grey',
            first_name='Grey',
            last_name='Golla'
        )
        login(request, obj)

    # TODO: this shouldn't be here
    page, _ = Page.objects.get_or_create(owner=request.user, date=datetime.date.today())
    for metric in ['mood', 'anxiety', 'cynicism']:
        Metric.objects.get_or_create(page=page, name=metric, defaults={
            'value': 1
        })

    return JsonResponse({
        "name": request.user.first_name,
        "page": page.date,
        "content": page.content
    })


def graph(request):
    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False,
            'error': 'Not logged in!'
        })

    output = []

    for page in Page.objects.filter(owner=request.user).order_by('date'):
        output.append({
            'date': page.date,
            'metrics': {a: b for a, b in page.metric_set.values_list('name', 'value')}
        })

    return JsonResponse({
        'data': output
    })


def pointsOfInterest(request):
    lat = request.GET.get('latitude')
    long = request.GET.get('longitude')
    pois = getPOIS(lat, long)
    return JsonResponse(pois)


def wiki(request):
    content = requests.get('https://en.wikipedia.org/w/api.php?action=parse&format=json&page={}'.format(request.GET.get('q'))).json()["parse"]

    return JsonResponse({
        'title': content['title'],
        'content': content['text']['*']
    })
