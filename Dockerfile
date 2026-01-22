FROM php:8.3-fpm-alpine

# Argumentos
ARG USER_ID=1000
ARG GROUP_ID=1000

# Instala dependências do sistema
RUN apk add --no-cache \
    git \
    curl \
    libpng-dev \
    libjpeg-turbo-dev \
    freetype-dev \
    libzip-dev \
    zip \
    unzip \
    postgresql-dev \
    icu-dev \
    oniguruma-dev \
    linux-headers \
    $PHPIZE_DEPS

# Configura e instala extensões PHP
RUN docker-php-ext-configure gd --with-freetype --with-jpeg
RUN docker-php-ext-install \
    pdo \
    pdo_pgsql \
    pgsql \
    gd \
    zip \
    intl \
    mbstring \
    exif \
    pcntl \
    bcmath \
    opcache

# Instala Redis extension
RUN pecl install redis && docker-php-ext-enable redis

# Instala Composer
COPY --from=composer:latest /usr/bin/composer /usr/bin/composer

# Cria usuário não-root
RUN addgroup -g ${GROUP_ID} plattargus && \
    adduser -u ${USER_ID} -G plattargus -s /bin/sh -D plattargus

# Configura PHP
COPY docker/php/local.ini /usr/local/etc/php/conf.d/local.ini

# Define diretório de trabalho
WORKDIR /var/www

# Copia arquivos do projeto
COPY --chown=plattargus:plattargus . /var/www

# Instala dependências do Composer
RUN composer install --no-dev --optimize-autoloader --no-interaction

# Permissões
RUN chown -R plattargus:plattargus /var/www/storage /var/www/bootstrap/cache

# Troca para usuário não-root
USER plattargus

# Expõe porta
EXPOSE 9000

# Comando padrão
CMD ["php-fpm"]
