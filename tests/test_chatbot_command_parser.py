"""Tests for chatbot workflow command parser."""

from __future__ import annotations

from app.services.chatbot_command_parser import (
    INTENT_KEYWORD_CLUSTER_TO_ARTICLE,
    build_workflow_reply,
    clear_pending_workflow,
    parse_chatbot_command,
)


def test_normal_message_not_workflow():
    r = parse_chatbot_command("Giá phần mềm bao nhiêu?")
    assert r.intent is None
    assert not r.is_workflow


def test_cluster_to_article_with_keyword_vi():
    r = parse_chatbot_command("Gom nhóm từ khóa đào tạo SEO và viết bài cho tôi")
    assert r.intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE
    assert r.primary_keyword == "đào tạo SEO"
    assert not r.needs_keyword


def test_cluster_to_article_research_vi():
    r = parse_chatbot_command("Research từ khóa bất động sản rồi viết bài SEO")
    assert r.intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE
    assert "bất động sản" in (r.primary_keyword or "")


def test_cluster_to_article_extracts_metadata():
    msg = (
        "Gom nhóm từ khóa phần mềm CRM và viết bài blog 1500 từ, "
        "tiếng Việt, tone chuyên nghiệp, thị trường Việt Nam"
    )
    r = parse_chatbot_command(msg)
    assert r.intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE
    assert r.primary_keyword == "phần mềm CRM"
    assert r.word_count == 1500
    assert r.language == "vi"
    assert r.tone == "professional"
    assert r.country == "VN"
    assert r.article_type == "blog"


def test_missing_keyword_asks_followup():
    clear_pending_workflow("sess_test_1")
    r = parse_chatbot_command(
        "Gom nhóm từ khóa và viết bài SEO giúp tôi",
        session_id="sess_test_1",
    )
    assert r.intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE
    assert r.needs_keyword
    assert "primary_keyword" in r.missing_fields
    reply = build_workflow_reply(r)
    assert "từ khóa chính" in reply.lower()
    assert "workflow" in reply.lower()


def test_followup_keyword_after_prompt():
    clear_pending_workflow("sess_test_2")
    parse_chatbot_command(
        "Research từ khóa rồi viết bài",
        session_id="sess_test_2",
    )
    history = [
        {
            "role": "assistant",
            "content": "Vui lòng cho biết **từ khóa chính** (workflow: keyword_cluster_to_article)",
        }
    ]
    r = parse_chatbot_command("đào tạo SEO", history=history, session_id="sess_test_2")
    assert r.intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE
    assert r.primary_keyword == "đào tạo SEO"
    reply = build_workflow_reply(r)
    assert "số từ" in reply.lower() or "1000" in reply


def test_workflow_detects_internal_link_and_images():
    r = parse_chatbot_command(
        "Gom nhóm từ khóa SEO rồi viết bài SEO có internal link và hình ảnh"
    )
    assert r.intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE
    assert r.include_internal_links
    assert r.needs_word_count
    assert r.image_source is None


def test_workflow_asks_word_count_when_missing():
    clear_pending_workflow("sess_wc_1")
    r = parse_chatbot_command(
        "Research từ khóa đào tạo SEO, gom nhóm và viết bài cho tôi",
        session_id="sess_wc_1",
    )
    assert r.intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE
    assert r.needs_word_count
    assert r.primary_keyword == "đào tạo SEO"
    reply = build_workflow_reply(r)
    assert "1000" in reply and "1500" in reply


def test_followup_word_count_after_prompt():
    clear_pending_workflow("sess_wc_2")
    parse_chatbot_command(
        "Gom nhóm từ khóa laptop và viết bài",
        session_id="sess_wc_2",
    )
    history = [
        {
            "role": "assistant",
            "content": "Bạn muốn bài dài bao nhiêu từ? (workflow: keyword_cluster_to_article)",
        }
    ]
    r = parse_chatbot_command("1500", history=history, session_id="sess_wc_2")
    assert r.word_count == 1500
    assert r.primary_keyword == "laptop"
    assert r.needs_image_source or r.awaiting_image_source


def test_followup_word_count_without_pending_uses_history():
    """Sau restart server pending in-memory mất — vẫn nhận số từ từ lịch sử chat."""
    clear_pending_workflow("sess_wc_3")
    history = [
        {
            "role": "assistant",
            "content": build_workflow_reply(
                parse_chatbot_command(
                    "Research từ khóa đào tạo SEO, gom nhóm và viết bài cho tôi",
                    session_id="sess_wc_3",
                )
            ),
        }
    ]
    clear_pending_workflow("sess_wc_3")
    r = parse_chatbot_command("1000", history=history, session_id="sess_wc_3")
    assert r.intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE
    assert r.word_count == 1000
    assert r.primary_keyword == "đào tạo SEO"
    assert r.needs_image_source or r.awaiting_image_source


def test_followup_word_count_button_label():
    clear_pending_workflow("sess_wc_4")
    history = [
        {
            "role": "assistant",
            "content": (
                "Mình nhận diện workflow **Research → Gom nhóm → Viết bài SEO**.\n\n"
                "- **Từ khóa chính:** laptop gaming\n\n"
                "Bạn muốn bài dài **bao nhiêu từ**?\n"
                "_(workflow: keyword_cluster_to_article)_"
            ),
        }
    ]
    r = parse_chatbot_command("2000 từ", history=history, session_id="sess_wc_4")
    assert r.word_count == 2000
    assert r.primary_keyword == "laptop gaming"
    assert r.needs_image_source or r.awaiting_image_source


def test_followup_image_source_after_word_count():
    clear_pending_workflow("sess_img_1")
    history = [
        {
            "role": "assistant",
            "content": (
                "Mình nhận diện workflow **Research → Gom nhóm → Viết bài SEO**.\n\n"
                "- **Từ khóa chính:** spa thư giãn\n"
                "- **Số từ:** 1500\n"
                "Bạn muốn **nguồn ảnh** nào?\n"
                "_(workflow: keyword_cluster_to_article)_"
            ),
        }
    ]
    r = parse_chatbot_command("tạo ảnh bằng ai", history=history, session_id="sess_img_1")
    assert r.image_source == "ai"
    assert r.include_images
    assert r.word_count == 1500
    assert r.primary_keyword == "spa thư giãn"


def test_create_article_from_keyword_cluster_phrase():
    r = parse_chatbot_command("Tạo bài viết từ cụm keyword laptop gaming")
    assert r.intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE
    assert r.primary_keyword == "laptop gaming"


def test_write_article_with_keyword_natural_vi():
    r = parse_chatbot_command(
        "viết cho tôi bài viết với từ khóa dịch vụ quảng cáo facebook"
    )
    assert r.intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE
    assert r.primary_keyword == "dịch vụ quảng cáo facebook"
    assert r.needs_word_count
    assert not r.needs_keyword


def test_write_article_keyword_at_end_of_sentence():
    r = parse_chatbot_command("Viết bài SEO từ khóa thiết kế website")
    assert r.intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE
    assert r.primary_keyword == "thiết kế website"


def test_write_article_with_keyword_and_word_count():
    r = parse_chatbot_command(
        "Tạo bài viết với từ khóa phần mềm CRM, 1500 từ"
    )
    assert r.primary_keyword == "phần mềm CRM"
    assert r.word_count == 1500
    assert r.needs_image_source or r.awaiting_image_source
