import type { ButtonHTMLAttributes } from 'react';
import './LinkButton.css';

export function LinkButton({ className, type = 'button', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...props} type={type} className={'link link-button' + (className ? ' ' + className : '')} />;
}
