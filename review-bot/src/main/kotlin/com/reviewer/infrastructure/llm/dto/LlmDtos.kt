package com.reviewer.infrastructure.llm.dto

// --- vLLM / OpenAI-compatible Request ---

data class ChatCompletionRequest(
    val model: String,
    val messages: List<ChatMessage>,
    val temperature: Double = 0.1,
    val maxTokens: Int = 4096,
    val topP: Double? = null,
    val stop: List<String>? = null,
    val stream: Boolean = false,
)

data class ChatMessage(
    val role: String,
    val content: String,
)

// --- vLLM / OpenAI-compatible Response ---

data class ChatCompletionResponse(
    val id: String,
    val objectType: String? = null,
    val created: Long = 0,
    val model: String,
    val choices: List<ChatChoice> = emptyList(),
    val usage: TokenUsage? = null,
)

data class ChatChoice(
    val index: Int = 0,
    val message: ChatMessage? = null,
    val finishReason: String? = null,
)

data class TokenUsage(
    val promptTokens: Int = 0,
    val completionTokens: Int = 0,
    val totalTokens: Int = 0,
)

// --- Claude Messages API Request ---

data class ClaudeMessagesRequest(
    val model: String,
    val maxTokens: Int,
    val system: String? = null,
    val messages: List<ClaudeMessage>,
    val temperature: Double? = null,
    val stream: Boolean = false,
)

data class ClaudeMessage(
    val role: String,
    val content: String,
)

// --- Claude Messages API Response ---

data class ClaudeMessagesResponse(
    val id: String,
    val type: String,
    val role: String,
    val content: List<ClaudeContent>,
    val model: String,
    val stopReason: String?,
    val usage: ClaudeUsage,
)

data class ClaudeContent(
    val type: String,
    val text: String? = null,
)

data class ClaudeUsage(
    val inputTokens: Int = 0,
    val outputTokens: Int = 0,
)

// --- Review-specific ---

data class ReviewLlmResponse(
    val content: String,
    val model: String,
    val provider: String,
    val inputTokens: Int = 0,
    val outputTokens: Int = 0,
    val totalTokens: Int = 0,
)
