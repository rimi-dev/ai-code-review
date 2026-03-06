package com.reviewer.config

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.data.redis.connection.ReactiveRedisConnectionFactory
import org.springframework.data.redis.connection.stream.ObjectRecord
import org.springframework.data.redis.core.ReactiveRedisTemplate
import org.springframework.data.redis.serializer.RedisSerializationContext
import org.springframework.data.redis.serializer.StringRedisSerializer
import org.springframework.data.redis.stream.StreamReceiver
import java.time.Duration

@Configuration
class RedisConfig {

    @Bean
    fun reactiveRedisTemplate(
        connectionFactory: ReactiveRedisConnectionFactory,
    ): ReactiveRedisTemplate<String, String> {
        val context = RedisSerializationContext.newSerializationContext<String, String>(
            StringRedisSerializer()
        )
            .value(StringRedisSerializer())
            .hashKey(StringRedisSerializer())
            .hashValue(StringRedisSerializer())
            .build()

        return ReactiveRedisTemplate(connectionFactory, context)
    }

    @Bean
    fun streamReceiver(
        connectionFactory: ReactiveRedisConnectionFactory,
    ): StreamReceiver<String, ObjectRecord<String, String>> {
        val options = StreamReceiver.StreamReceiverOptions.builder()
            .pollTimeout(Duration.ofSeconds(2))
            .batchSize(10)
            .targetType(String::class.java)
            .build()

        return StreamReceiver.create(connectionFactory, options)
    }
}
