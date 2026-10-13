from django.db import transaction

# resend OTP email
if email_id:
    try:
        user = UserMaster.objects.get(email_id__iexact=email_id)
    except UserMaster.DoesNotExist:
        return Response({'status': False, 'message': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"reset_password lookup failed: email={email_id}, error={e}")
        return Response({'status': False, 'message': 'Something went wrong. Please try again.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    try:
        last_token = PasswordResetToken.objects.filter(user=user).order_by('-created_at').first()
        if last_token:
            seconds_since_last = (timezone.now() - last_token.created_at).total_seconds()
            if seconds_since_last < self.RESEND_COOLDOWN_SECONDS:
                wait_remaining = int(self.RESEND_COOLDOWN_SECONDS - seconds_since_last)
                logger.warning(f"OTP resend blocked: too soon user_id={user.user_id}, wait={wait_remaining}s")
                return Response(
                    {'status': False, 'message': f'Please wait {wait_remaining} seconds before requesting another OTP.'},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

        with transaction.atomic():
            # Lock and invalidate ALL previous unused tokens for this user first
            invalidated_count = PasswordResetToken.objects.select_for_update().filter(
                user=user, is_used=False
            ).update(is_used=True)

            otp = generate_otp()
            reset_token = PasswordResetToken.objects.create(
                user       = user,
                token      = uuid.uuid4(),
                otp_code   = otp,
                is_used    = False,
                expires_at = timezone.now() + timedelta(minutes=10),
            )

        logger.info(
            f"OTP token created: user_id={user.user_id}, invalidated_previous={invalidated_count}"
        )

    except Exception as e:
        logger.error(f"OTP generation failed: email={email_id}, user_id={user.user_id}, error={e}")
        return Response({'status': False, 'message': 'Failed to generate OTP. Please try again.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)