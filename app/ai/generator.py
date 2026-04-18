import openai
from typing import Optional
import random
from app.core.config import get_settings

settings = get_settings()

# Initialize OpenAI
openai.api_key = settings.openai_api_key

# Casual email topics for warm-up
EMAIL_TOPICS = [
    "weekend plans",
    "favorite coffee shop recommendation",
    "book recommendation",
    "podcast suggestion",
    "movie recommendation",
    "travel experience",
    "local restaurant review",
    "hobby discussion",
    "weather observations",
    "pet stories",
    "recipe sharing",
    "music recommendations",
    "fitness tips",
    "work-life balance",
    "home organization",
]

# Safety rules for AI generation
SAFETY_INSTRUCTIONS = """
CRITICAL SAFETY RULES - DO NOT VIOLATE:
1. NO URLs, links, or website mentions
2. NO sales language, promotional content, or CTAs
3. NO business propositions or networking requests
4. NO requests for personal information
5. Keep replies 1-3 sentences maximum
6. Sound casual, friendly, and natural
7. Focus on conversational topics only
8. NO marketing jargon or buzzwords
9. Vary your tone and phrasing
10. Act like a real human having a casual conversation
"""


def generate_casual_email(topic: Optional[str] = None) -> tuple[str, str]:
    """Generate a casual, non-promotional email"""
    if not topic:
        topic = random.choice(EMAIL_TOPICS)
    
    prompt = f"""{SAFETY_INSTRUCTIONS}

Write a short, casual email about: {topic}

Requirements:
- 2-4 sentences maximum
- Friendly and conversational tone
- Sound like a real person
- No links, no sales, no CTAs
- Just a friendly message

Return format:
Subject: [one line subject]
Body: [email body]
"""
    
    try:
        response = openai.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": "You are a friendly person writing casual emails to friends."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=settings.openai_max_tokens,
            temperature=0.9,  # Higher temperature for variety
        )
        
        content = response.choices[0].message.content.strip()
        
        # Parse subject and body
        lines = content.split('\n')
        subject = ""
        body = ""
        
        for line in lines:
            if line.startswith("Subject:"):
                subject = line.replace("Subject:", "").strip()
            elif line.strip() and not line.startswith("Body:"):
                body += line.strip() + " "
        
        if not subject:
            subject = f"Hey! About {topic}"
        
        if not body:
            body = content
        
        # Validate safety
        if not is_content_safe(subject + " " + body):
            # Fall back to super safe email
            return generate_safe_fallback_email(topic)
        
        return subject.strip(), body.strip()
        
    except Exception as e:
        print(f"Error generating email: {e}")
        return generate_safe_fallback_email(topic)


def generate_reply(original_subject: str, original_body: str) -> str:
    """Generate a casual reply to an email"""
    prompt = f"""{SAFETY_INSTRUCTIONS}

Original email:
Subject: {original_subject}
Body: {original_body}

Write a short, friendly reply (1-3 sentences). Sound natural and human.
NO links, sales language, or CTAs. Just a casual, friendly response.
"""
    
    try:
        response = openai.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": "You are replying to a friendly email from a friend."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=settings.openai_max_tokens,
            temperature=0.9,
        )
        
        reply = response.choices[0].message.content.strip()
        
        # Validate safety
        if not is_content_safe(reply):
            return generate_safe_fallback_reply()
        
        return reply
        
    except Exception as e:
        print(f"Error generating reply: {e}")
        return generate_safe_fallback_reply()


def is_content_safe(content: str) -> bool:
    """Check if content is safe (no links, no sales language)"""
    content_lower = content.lower()
    
    # Check for URLs
    url_patterns = ['http://', 'https://', 'www.', '.com', '.net', '.org', 'click here', 'visit']
    if any(pattern in content_lower for pattern in url_patterns):
        return False
    
    # Check for sales/marketing language
    sales_patterns = [
        'buy', 'purchase', 'discount', 'offer', 'deal', 'sale', 'limited time',
        'click', 'sign up', 'subscribe', 'register', 'download', 'free trial',
        'learn more', 'contact us', 'schedule', 'book now', 'order', 'product'
    ]
    if any(pattern in content_lower for pattern in sales_patterns):
        return False
    
    return True


def generate_safe_fallback_email(topic: str) -> tuple[str, str]:
    """Generate a guaranteed safe fallback email"""
    templates = [
        ("Quick thought", f"Just wanted to share that I've been thinking about {topic}. Hope you're having a great day!"),
        ("Hey there", f"I was reminded of our conversation about {topic}. How have you been?"),
        ("Checking in", f"Haven't chatted in a bit! Been exploring {topic} lately. What's new with you?"),
    ]
    
    subject, body = random.choice(templates)
    return subject, body


def generate_safe_fallback_reply() -> str:
    """Generate a guaranteed safe fallback reply"""
    replies = [
        "That sounds really interesting! Thanks for sharing.",
        "Oh nice! I appreciate you thinking of me.",
        "That's cool! Hope you're doing well.",
        "Interesting perspective! Thanks for the message.",
        "That's great! Good to hear from you.",
    ]
    
    return random.choice(replies)


def calculate_reply_delay() -> int:
    """Calculate human-like reply delay in minutes"""
    # Random delay between 30 minutes and 8 hours
    return random.randint(30, 480)
