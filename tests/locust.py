from locust import HttpUser, task, between
import random

# нагружаем сервис созданием ссылок и невалидными запросами
class UrlShortenerUser(HttpUser):
    wait_time = between(1, 3)

    @task(1)
    def create_link(self):
        rand_str = str(random.randint(1000, 9999))
        self.client.post("/links/shorten", json={
            "original_url": f"https://example.com/{rand_str}"
        })

    @task(3)
    def visit_link(self):
        self.client.get("/some_random_code", follow_redirects=False)