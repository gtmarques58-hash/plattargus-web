<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class TemplateDocumento extends Model
{
    protected $table = 'templates_documento';
    
    protected $fillable = [
        'codigo',
        'tipo_sei',
        'categoria',
        'nome',
        'descricao',
        'conteudo_html',
        'campos',
        'remetente_tipo',
        'ativo',
        'ordem',
    ];
    
    protected $casts = [
        'campos' => 'array',
        'ativo' => 'boolean',
    ];
    
    /**
     * Retorna templates ativos ordenados
     */
    public function scopeAtivos($query)
    {
        return $query->where('ativo', true)->orderBy('ordem')->orderBy('nome');
    }
    
    /**
     * Filtra por tipo SEI
     */
    public function scopePorTipo($query, string $tipoSei)
    {
        return $query->where('tipo_sei', $tipoSei);
    }
    
    /**
     * Filtra por categoria
     */
    public function scopePorCategoria($query, string $categoria)
    {
        return $query->where('categoria', $categoria);
    }
    
    /**
     * Preenche o template com os dados fornecidos
     */
    public function preencher(array $dados): string
    {
        $html = $this->conteudo_html;
        
        foreach ($dados as $campo => $valor) {
            $placeholder = '{' . $campo . '}';
            $html = str_replace($placeholder, $valor ?? '', $html);
        }
        
        return $html;
    }
    
    /**
     * Valida se todos os campos obrigatórios foram fornecidos
     */
    public function validarCampos(array $dados): array
    {
        $faltantes = [];
        
        if ($this->campos) {
            foreach ($this->campos as $campo) {
                if (!isset($dados[$campo]) || empty($dados[$campo])) {
                    $faltantes[] = $campo;
                }
            }
        }
        
        return $faltantes;
    }
    
    /**
     * Retorna se o remetente deve ser o usuário logado
     */
    public function isRemetenteUsuario(): bool
    {
        return in_array($this->remetente_tipo, ['usuario_logado', 'requerente']);
    }
    
    /**
     * Retorna se o remetente deve ser o chefe da unidade
     */
    public function isRemetenteChefe(): bool
    {
        return $this->remetente_tipo === 'chefe_unidade';
    }
}
