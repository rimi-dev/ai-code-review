package com.reviewer.config

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.data.redis.connection.ReactiveRedisConnectionFactory
import org.springframework.data.redis.core.ReactiveRedisTemplate
import org.springframework.data.redis.serializer.RedisSerializationContext
import org.springframework.data.redis.serializer.StringRedisSerializer

@Configuration
class RedisConfig {
    @Bean
    @org.springframework.context.annotation.Primary
    fun reactiveRedisTemplate(
        connectionFactory: ReactiveRedisConnectionFactory,
    ): ReactiveRedisTemplate<String, String> {
        val context = RedisSerializationContext.newSerializationContext<String, String>(StringRedisSerializer())
            .value(StringRedisSerializer())
            .build()
        return ReactiveRedisTemplate(connectionFactory, context)
    }
}
