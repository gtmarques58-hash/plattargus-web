<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Foundation\Auth\User as Authenticatable;
use Illuminate\Notifications\Notifiable;
use Laravel\Sanctum\HasApiTokens;
use Spatie\Permission\Traits\HasRoles;
use App\Services\CredentialVaultService;

class User extends Authenticatable
{
    use HasApiTokens, HasFactory, Notifiable, HasRoles;

    /**
     * The attributes that are mass assignable.
     */
    protected $fillable = [
        'usuario_sei',
        'matricula',
        'password',
        'nome_completo',
        'posto_grad',
        'cargo',
        'unidade',
        
        // Credencial SEI
        'sei_senha_cipher',
        'sei_senha_iv',
        'sei_senha_tag',
        'sei_orgao_id',
        'sei_cargo',
        'sei_credencial_ativa',
        
        // Controle
        'ativo',
        'primeiro_acesso',
    ];

    /**
     * The attributes that should be hidden for serialization.
     */
    protected $hidden = [
        'password',
        'remember_token',
        'sei_senha_cipher',
        'sei_senha_iv',
        'sei_senha_tag',
    ];

    /**
     * The attributes that should be cast.
     */
    protected $casts = [
        'password' => 'hashed',
        
        'sei_credencial_ativa' => 'boolean',
        'ativo' => 'boolean',
        'primeiro_acesso' => 'boolean',
        'ultimo_acesso' => 'datetime',
        'created_at' => 'datetime',
        'updated_at' => 'datetime',
    ];

    /**
     * Boot the model.
     */
    protected static function boot()
    {
        parent::boot();

        // Sempre converter usuario_sei para minúsculas
        static::creating(function ($user) {
            $user->usuario_sei = strtolower(trim($user->usuario_sei));
        });

        static::updating(function ($user) {
            $user->usuario_sei = strtolower(trim($user->usuario_sei));
        });
    }

    // =========================================================================
    // RELACIONAMENTOS
    // =========================================================================

    /**
     * Processos analisados pelo usuário.
     */
    public function processAnalyses()
    {
        return $this->hasMany(ProcessAnalysis::class);
    }

    /**
     * Jobs do usuário.
     */
    public function jobs()
    {
        return $this->hasMany(Job::class);
    }

    /**
     * Logs de auditoria do usuário.
     */
    public function auditLogs()
    {
        return $this->hasMany(AuditLog::class);
    }

    // =========================================================================
    // CREDENCIAL SEI
    // =========================================================================

    /**
     * Verifica se o usuário tem credencial SEI cadastrada.
     */
    public function hasCredencialSei(): bool
    {
        if (!$this->sei_credencial_ativa) {
            return false;
        }
        
        // Verificar se os campos existem (podem ser resource ou string)
        $cipher = $this->sei_senha_cipher;
        $iv = $this->sei_senha_iv;
        $tag = $this->sei_senha_tag;
        
        // Converter resource para verificação
        if (is_resource($cipher)) {
            $pos = ftell($cipher);
            rewind($cipher);
            $content = stream_get_contents($cipher);
            fseek($cipher, $pos); // Volta posição original
            $cipher = $content;
        }
        
        return !empty($cipher) && !empty($iv) && !empty($tag);
    }

    /**
     * Salva a credencial SEI criptografada.
     */
    public function setCredencialSei(string $senhaSei, string $orgaoId = '31', string $cargo = null): void
    {
        $vault = app(CredentialVaultService::class);
        $encrypted = $vault->encrypt($senhaSei);

        $this->sei_senha_cipher = $encrypted['ciphertext'];
        $this->sei_senha_iv = $encrypted['iv'];
        $this->sei_senha_tag = $encrypted['tag'];
        $this->sei_orgao_id = $orgaoId;
        $this->sei_cargo = $cargo;
        $this->sei_credencial_ativa = true;
        $this->save();
    }

    /**
     * Obtém a credencial SEI descriptografada.
     * ATENÇÃO: Use apenas quando necessário e limpe da memória após uso.
     */
    public function getCredencialSei(): ?array
    {
        if (!$this->hasCredencialSei()) {
            return null;
        }
        
        $vault = app(CredentialVaultService::class);
        
        try {
            // Converter resource para string (PostgreSQL bytea)
            $cipher = $this->sei_senha_cipher;
            $iv = $this->sei_senha_iv;
            $tag = $this->sei_senha_tag;
            
            if (is_resource($cipher)) {
                $cipher = stream_get_contents($cipher);
            }
            if (is_resource($iv)) {
                $iv = stream_get_contents($iv);
            }
            if (is_resource($tag)) {
                $tag = stream_get_contents($tag);
            }
            
            $senhaSei = $vault->decrypt($cipher, $iv, $tag);
            
            return [
                'usuario' => $this->usuario_sei,
                'senha' => $senhaSei,
                'orgao_id' => $this->sei_orgao_id,
                'cargo' => $this->sei_cargo,
            ];
        } catch (\Exception $e) {
            \Log::error('Erro ao descriptografar credencial SEI', [
                'user_id' => $this->id,
                'error' => $e->getMessage(),
            ]);
            return null;
        }
    }

    /**
     * Remove a credencial SEI.
     */
    public function removeCredencialSei(): void
    {
        $this->sei_senha_cipher = null;
        $this->sei_senha_iv = null;
        $this->sei_senha_tag = null;
        $this->sei_credencial_ativa = false;
        $this->save();
    }

    // =========================================================================
    // SCOPES
    // =========================================================================

    /**
     * Scope para usuários ativos.
     */
    public function scopeAtivos($query)
    {
        return $query->where('ativo', true);
    }

    /**
     * Scope para usuários com credencial SEI.
     */
    public function scopeComCredencialSei($query)
    {
        return $query->where('sei_credencial_ativa', true);
    }

    /**
     * Scope para usuários em primeiro acesso.
     */
    public function scopePrimeiroAcesso($query)
    {
        return $query->where('primeiro_acesso', true);
    }

    // =========================================================================
    // HELPERS
    // =========================================================================

    /**
     * Nome formatado para exibição.
     */
    public function getNomeExibicaoAttribute(): string
    {
        if ($this->posto_grad && $this->nome_completo) {
            return "{$this->posto_grad} {$this->nome_completo}";
        }
        
        return $this->nome_completo ?? $this->usuario_sei;
    }

    /**
     * Registra último acesso.
     */
    public function registrarAcesso(): void
    {
        $this->ultimo_acesso = now();
        $this->save();
    }

    /**
     * Marca primeiro acesso como concluído.
     */
    public function concluirPrimeiroAcesso(): void
    {
        $this->primeiro_acesso = false;
        $this->save();
    }
}
