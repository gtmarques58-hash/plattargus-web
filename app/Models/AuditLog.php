<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/**
 * AuditLog - Registro de Auditoria Imutável
 * 
 * Registra todas as ações sensíveis do sistema para compliance e rastreabilidade.
 */
class AuditLog extends Model
{
    /**
     * Desabilita timestamps automáticos (usamos apenas created_at).
     */
    public $timestamps = false;

    /**
     * The attributes that are mass assignable.
     */
    protected $fillable = [
        'user_id',
        'action',
        'target_type',
        'target_id',
        'status',
        'ip_address',
        'user_agent',
        'metadata',
    ];

    /**
     * The attributes that should be cast.
     */
    protected $casts = [
        'metadata' => 'array',
        'created_at' => 'datetime',
    ];

    /**
     * Boot the model.
     */
    protected static function boot()
    {
        parent::boot();

        // Sempre define created_at na criação
        static::creating(function ($log) {
            $log->created_at = now();
        });

        // IMPEDE atualizações (imutável)
        static::updating(function ($log) {
            return false;
        });

        // IMPEDE deleções (imutável)
        static::deleting(function ($log) {
            return false;
        });
    }

    // =========================================================================
    // RELACIONAMENTOS
    // =========================================================================

    /**
     * Usuário que executou a ação.
     */
    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }

    // =========================================================================
    // SCOPES
    // =========================================================================

    /**
     * Filtra por ação.
     */
    public function scopeAction($query, string $action)
    {
        return $query->where('action', $action);
    }

    /**
     * Filtra por status.
     */
    public function scopeStatus($query, string $status)
    {
        return $query->where('status', $status);
    }

    /**
     * Filtra por usuário.
     */
    public function scopeForUser($query, int $userId)
    {
        return $query->where('user_id', $userId);
    }

    /**
     * Filtra por período.
     */
    public function scopeBetween($query, $start, $end)
    {
        return $query->whereBetween('created_at', [$start, $end]);
    }

    /**
     * Apenas sucessos.
     */
    public function scopeSuccessful($query)
    {
        return $query->where('status', 'success');
    }

    /**
     * Apenas falhas.
     */
    public function scopeFailed($query)
    {
        return $query->where('status', 'failure');
    }

    /**
     * Últimos N registros.
     */
    public function scopeRecent($query, int $limit = 50)
    {
        return $query->orderBy('created_at', 'desc')->limit($limit);
    }

    // =========================================================================
    // HELPERS ESTÁTICOS
    // =========================================================================

    /**
     * Registra uma ação de forma simplificada.
     */
    public static function log(
        ?int $userId,
        string $action,
        string $status = 'success',
        ?string $targetType = null,
        ?string $targetId = null,
        array $metadata = []
    ): self {
        return self::create([
            'user_id' => $userId,
            'action' => $action,
            'target_type' => $targetType,
            'target_id' => $targetId,
            'status' => $status,
            'ip_address' => request()->ip(),
            'user_agent' => request()->userAgent(),
            'metadata' => $metadata,
        ]);
    }

    /**
     * Registra login bem-sucedido.
     */
    public static function logLogin(int $userId): self
    {
        return self::log($userId, 'login', 'success');
    }

    /**
     * Registra falha de login.
     */
    public static function logLoginFailed(string $usuarioSei): self
    {
        return self::log(null, 'login_failed', 'failure', 'user', $usuarioSei);
    }

    /**
     * Registra logout.
     */
    public static function logLogout(int $userId): self
    {
        return self::log($userId, 'logout', 'success');
    }

    /**
     * Registra cadastro de credencial SEI.
     */
    public static function logCredentialCreate(int $userId): self
    {
        return self::log($userId, 'credential_create', 'success', 'sei_credential');
    }

    /**
     * Registra uso de credencial SEI (descriptografia).
     */
    public static function logCredentialUse(int $userId, string $action, string $target): self
    {
        return self::log($userId, 'credential_use', 'success', $action, $target);
    }

    /**
     * Registra assinatura de documento.
     */
    public static function logSign(int $userId, string $seiNumero, bool $success): self
    {
        return self::log(
            $userId, 
            'sign_document', 
            $success ? 'success' : 'failure',
            'document',
            $seiNumero
        );
    }

    // =========================================================================
    // ACCESSORS
    // =========================================================================

    /**
     * Descrição legível da ação.
     */
    public function getActionDescriptionAttribute(): string
    {
        $descriptions = [
            'login' => 'Login no sistema',
            'login_failed' => 'Tentativa de login falhou',
            'logout' => 'Logout do sistema',
            'credential_create' => 'Cadastrou credencial SEI',
            'credential_use' => 'Usou credencial SEI',
            'step_up_granted' => 'Autorização step-up concedida',
            'step_up_invalid_password' => 'Senha incorreta no step-up',
            'step_up_locked_out' => 'Bloqueado por tentativas excessivas',
            'analisar_processo' => 'Analisou processo',
            'gerar_documento' => 'Gerou documento',
            'sign_document' => 'Assinou documento',
            'inserir_sei' => 'Inseriu documento no SEI',
        ];

        return $descriptions[$this->action] ?? $this->action;
    }

    /**
     * Ícone para a ação.
     */
    public function getActionIconAttribute(): string
    {
        $icons = [
            'login' => '🔐',
            'login_failed' => '❌',
            'logout' => '🚪',
            'credential_create' => '🔑',
            'credential_use' => '🔓',
            'step_up_granted' => '✅',
            'step_up_invalid_password' => '🚫',
            'step_up_locked_out' => '🔒',
            'analisar_processo' => '🔍',
            'gerar_documento' => '📄',
            'sign_document' => '✍️',
            'inserir_sei' => '📤',
        ];

        return $icons[$this->action] ?? '📋';
    }
}
