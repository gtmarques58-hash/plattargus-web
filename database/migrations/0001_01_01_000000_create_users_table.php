<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    /**
     * Run the migrations.
     */
    public function up(): void
    {
        Schema::create('users', function (Blueprint $table) {
            $table->id();
            
            // =========================================================
            // IDENTIFICAÇÃO (TRAVADO - usuário SEI é a chave)
            // =========================================================
            $table->string('usuario_sei', 100)->unique();
            
            // =========================================================
            // AUTENTICAÇÃO PLATTARGUS
            // =========================================================
            $table->string('password');  // bcrypt - senha do PlattArgus
            $table->rememberToken();
            
            // =========================================================
            // DADOS PESSOAIS
            // =========================================================
            $table->string('nome_completo', 255)->nullable();
            $table->string('posto_grad', 50)->nullable();    // MAJ QOBMEC
            $table->string('cargo', 100)->nullable();        // Diretor de RH
            $table->string('unidade', 100)->nullable();      // DRH
            $table->string('email', 255)->nullable();        // Opcional
            
            // =========================================================
            // CREDENCIAL SEI (CRIPTOGRAFADA AES-256-GCM)
            // =========================================================
            $table->binary('sei_senha_cipher')->nullable();  // Senha cifrada
            $table->binary('sei_senha_iv')->nullable();      // IV (12 bytes)
            $table->binary('sei_senha_tag')->nullable();     // Tag (16 bytes)
            $table->string('sei_orgao_id', 10)->default('31'); // CBMAC
            $table->string('sei_cargo', 100)->nullable();    // Cargo para assinatura
            $table->boolean('sei_credencial_ativa')->default(false);
            
            // =========================================================
            // CONTROLE DE ACESSO
            // =========================================================
            $table->boolean('ativo')->default(true);
            $table->boolean('primeiro_acesso')->default(true);
            $table->timestamp('ultimo_acesso')->nullable();
            
            // =========================================================
            // TIMESTAMPS
            // =========================================================
            $table->timestamps();
            
            // =========================================================
            // ÍNDICES
            // =========================================================
            $table->index('ativo');
            $table->index('sei_credencial_ativa');
            $table->index('unidade');
        });

        // =========================================================
        // TABELA DE SESSÕES (para invalidação)
        // =========================================================
        Schema::create('sessions', function (Blueprint $table) {
            $table->string('id')->primary();
            $table->foreignId('user_id')->nullable()->index();
            $table->string('ip_address', 45)->nullable();
            $table->text('user_agent')->nullable();
            $table->longText('payload');
            $table->integer('last_activity')->index();
        });

        // =========================================================
        // TABELA PASSWORD RESET (Laravel padrão)
        // =========================================================
        Schema::create('password_reset_tokens', function (Blueprint $table) {
            $table->string('email')->primary();
            $table->string('token');
            $table->timestamp('created_at')->nullable();
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('password_reset_tokens');
        Schema::dropIfExists('sessions');
        Schema::dropIfExists('users');
    }
};
